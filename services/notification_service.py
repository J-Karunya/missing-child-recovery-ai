"""Authorized, database-backed notifications for the human review workflow.

The default provider is deliberately local: it records a successful in-app
delivery in SQLite and never contacts SMS, email, or push services.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .review_store import ReviewStore, ValidationError, _now, _row


NOTIFICATION_STATUSES = {"PENDING", "SENT", "DELIVERED", "READ", "FAILED", "CANCELLED"}
MAX_METADATA_BYTES = 4096


class NotificationProvider(Protocol):
    """Future external providers must implement this narrow, testable boundary."""

    def send_notification(self, notification_id: int) -> str: ...


class DatabaseNotificationProvider:
    """Safe default provider: marks an in-app notification as sent locally."""

    def __init__(self, store: ReviewStore) -> None:
        self.store = store

    def send_notification(self, notification_id: int) -> str:
        with self.store._connection() as db:
            notification = _row(db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone())
            if not notification:
                raise ValidationError("Notification does not exist.")
            if notification["status"] == "PENDING":
                db.execute("UPDATE notifications SET status='SENT', sent_at=? WHERE id=?", (_now(), notification_id))
        return "SENT"


def parent_template(event: str, case_id: str) -> tuple[str, str, str]:
    """Return deliberately conservative wording without evidence or score data."""
    messages = {
        "PENDING": (
            "Potential match under review",
            "Potential match detected for your missing-child case. The case is currently under authorized review. Please do not take independent action based on this notification.",
            "HIGH",
        ),
        "VERIFIED": (
            "Important case update",
            "Your case has received an important update from an authorized reviewer. Please follow instructions provided through the official case process.",
            "HIGH",
        ),
        "REJECTED": (
            "Case review update",
            "An authorized review has updated a potential-match record for your case. Your case remains under the official process.",
            "NORMAL",
        ),
    }
    if event not in messages:
        raise ValidationError("Unsupported notification event.")
    return messages[event]


def internal_template(event: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Return staff-only content using controlled references, never raw file paths."""
    title = {
        "PENDING": "Potential match requires review",
        "VERIFIED": "Potential match verified by authorized reviewer",
        "REJECTED": "Potential match review rejected",
    }.get(event)
    if not title:
        raise ValidationError("Unsupported notification event.")
    details = [
        f"Case {context['case_id']}; child {context['child_id']}; potential match #{context['id']}.",
        f"CCTV source: {context['video_name']}; frame {context['frame_number']}; track {context['track_id']}; run {context['run_id']}.",
        f"Review status: {event}.",
    ]
    if context.get("overall_score") is not None:
        details.append(f"Explainable overall score: {context['overall_score']}.")
    if context.get("evidence_id") is not None:
        details.append(f"Controlled evidence reference: {context['evidence_id']}.")
    if context.get("last_observed"):
        details.append(f"Last observed camera: {context['last_observed']['camera_name']} ({context['last_observed']['camera_id']}) at {context['last_observed']['observed_at']}. CCTV observation only; not live GPS.")
    return title, " ".join(details), "HIGH" if event in {"PENDING", "VERIFIED"} else "NORMAL"


class NotificationService:
    """Creates deduplicated, role-safe notifications for an existing match."""

    def __init__(self, store: ReviewStore, provider: NotificationProvider | None = None) -> None:
        self.store = store
        self.provider = provider or DatabaseNotificationProvider(store)

    def notify_match_event(self, match_id: int, event: str) -> list[dict[str, Any]]:
        if event not in {"PENDING", "VERIFIED", "REJECTED"}:
            raise ValidationError("Unsupported notification event.")
        self.store.initialize()
        context = self.store.notification_match_context(match_id)
        stations = self.store.get_authorized_case_stations(context["case_id"])
        recipients = self._recipients(context, stations)
        created: list[dict[str, Any]] = []
        for recipient in recipients:
            parent = recipient["role"] == "PARENT"
            notification_type = ("PARENT" if parent else "STAFF") + f"_{event}"
            title, message, priority = parent_template(event, context["case_id"]) if parent else internal_template(event, context)
            notification = self._create(context, recipient, notification_type, title, message, priority, stations)
            if notification is not None:
                created.append(notification)
                self.store._audit_system("PARENT_NOTIFICATION_CREATED" if parent else "STATION_NOTIFICATION_CREATED", "notification", str(notification["id"]), {"case_id": context["case_id"], "potential_match_id": match_id, "recipient_role": recipient["role"], "event": event})
                self._deliver(notification["id"], context["case_id"])
        return created

    def _recipients(self, context: dict[str, Any], stations: list[str]) -> list[dict[str, Any]]:
        recipients: list[dict[str, Any]] = []
        parent_username = context.get("parent_username")
        with self.store._connection() as db:
            if parent_username:
                parent = _row(db.execute("SELECT id, username, role, station FROM users WHERE username=? AND role='PARENT' AND is_active=1", (parent_username,)).fetchone())
                if parent:
                    recipients.append(parent)
            if stations:
                placeholders = ",".join("?" for _ in stations)
                staff = db.execute(f"SELECT id, username, role, station FROM users WHERE is_active=1 AND role IN ('POLICE','REVIEWER') AND station IN ({placeholders})", stations).fetchall()
                recipients.extend(_row(row) for row in staff)
        return [recipient for recipient in recipients if recipient]

    def _create(self, context: dict[str, Any], recipient: dict[str, Any], notification_type: str, title: str, message: str, priority: str, stations: list[str]) -> dict[str, Any] | None:
        metadata = {"event": context["status"], "case_id": context["case_id"], "match_id": context["id"], "stations": stations}
        metadata_json = self._metadata(metadata)
        with self.store._connection() as db:
            try:
                cursor = db.execute("""INSERT INTO notifications(case_id, potential_match_id, recipient_user_id, recipient_role,
                    notification_type, channel, title, message, priority, status, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, 'IN_APP', ?, ?, ?, 'PENDING', ?, ?)""",
                    (context["case_id"], context["id"], recipient["id"], recipient["role"], notification_type, title, message, priority, _now(), metadata_json))
            except Exception as exc:
                # The unique constraint is intentional deduplication, not an error.
                if "UNIQUE constraint failed" in str(exc):
                    return None
                raise
            return _row(db.execute("SELECT * FROM notifications WHERE id=?", (cursor.lastrowid,)).fetchone())

    def _deliver(self, notification_id: int, case_id: str) -> None:
        try:
            status = self.provider.send_notification(notification_id)
            self.store._audit_system("NOTIFICATION_SENT", "notification", str(notification_id), {"case_id": case_id, "status": status, "channel": "IN_APP"})
        except Exception as exc:
            self.mark_failed_system(notification_id, str(exc))

    def mark_failed_system(self, notification_id: int, reason: str) -> None:
        safe_reason = str(reason).strip()[:300] or "Local provider failed."
        with self.store._connection() as db:
            notification = _row(db.execute("SELECT case_id FROM notifications WHERE id=?", (notification_id,)).fetchone())
            if not notification:
                raise ValidationError("Notification does not exist.")
            db.execute("UPDATE notifications SET status='FAILED', failure_reason=? WHERE id=?", (safe_reason, notification_id))
        self.store._audit_system("NOTIFICATION_FAILED", "notification", str(notification_id), {"case_id": notification["case_id"], "reason": safe_reason})

    @staticmethod
    def _metadata(value: dict[str, Any]) -> str:
        forbidden = ("password", "secret", "token", "api_key", "hash", "embedding")
        if any(any(word in str(key).lower() for word in forbidden) for key in value):
            raise ValidationError("Notification metadata contains a restricted field.")
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValidationError("Notification metadata exceeds the safe size limit.")
        return encoded
