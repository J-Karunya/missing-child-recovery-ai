import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.auth import build_session, session_expired
from services.notification_service import NotificationService, parent_template
from services.review_store import AuthorizationError, ReviewStore, ValidationError


PASSWORD = "correct-horse-battery-staple"


class Sprint6NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.temp.name) / "sprint6.db")
        self.store.initialize()
        self.store.create_user("admin", "ADMIN", "HQ", PASSWORD, "admin@example.test")
        for username, role, station in (("hq_police", "POLICE", "HQ"), ("local_police", "POLICE", "LOCAL"), ("other_police", "POLICE", "OTHER"), ("reviewer", "REVIEWER", "HQ"), ("parent", "PARENT", None), ("other_parent", "PARENT", None)):
            self.store.create_user(username, role, station, PASSWORD, f"{username}@example.test", actor="admin")
        self.store.create_case("hq_police", {"case_id": "CASE001", "child_id": "MC001", "child_name": "Child", "description": "Blue shirt", "reference_image": "child.jpg", "authorized_station": "HQ", "parent_username": "parent"})

    def tearDown(self):
        self.temp.cleanup()

    def _match(self, track=1):
        return self.store.record_potential_match({"case_id": "CASE001", "child_id": "MC001", "track_id": track, "run_id": "run-1", "frame_number": 12, "video_name": "station.mp4", "overall_score": 88.0, "evidence_path": "evidence.jpg", "metadata_path": "evidence.json", "reason": {"matched": ["clothing"]}})

    def test_schema_is_idempotent_and_has_notification_indexes(self):
        self.store.initialize()
        with self.store._connection() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(notifications)")}
            indexes = {row[1] for row in db.execute("PRAGMA index_list(notifications)")}
        self.assertTrue({"recipient_user_id", "status", "metadata_json", "failure_reason"}.issubset(columns))
        self.assertTrue(indexes)

    def test_pending_creates_parent_and_authorized_staff_notifications(self):
        self._match()
        parent = self.store.list_notifications("parent")
        hq = self.store.list_notifications("hq_police")
        self.assertEqual(len(parent), 1)
        self.assertIn("authorized review", parent[0]["message"])
        self.assertNotIn("88", parent[0]["message"])
        self.assertEqual(len(hq), 1)
        self.assertIn("Controlled evidence reference", hq[0]["message"])
        self.assertEqual(self.store.list_notifications("other_police"), [])

    def test_duplicate_event_does_not_create_unlimited_notifications(self):
        match = self._match()
        before = len(self.store.list_notifications("admin"))
        self.assertEqual(NotificationService(self.store).notify_match_event(match["id"], "PENDING"), [])
        self.assertEqual(len(self.store.list_notifications("admin")), before)

    def test_parent_isolation_and_notification_idor_are_rejected(self):
        self._match()
        notification = self.store.list_notifications("parent")[0]
        self.assertEqual(self.store.list_notifications("other_parent"), [])
        with self.assertRaises(AuthorizationError):
            self.store.mark_notification_read("other_parent", notification["id"])
        with self.assertRaises(AuthorizationError):
            self.store.mark_notification_read("other_police", notification["id"])

    def test_read_transition_is_audited(self):
        self._match()
        notification = self.store.list_notifications("parent")[0]
        read = self.store.mark_notification_read("parent", notification["id"])
        self.assertEqual(read["status"], "READ")
        self.assertTrue(read["read_at"])
        self.assertIn("NOTIFICATION_READ", [item["action"] for item in self.store.list_audit_logs("admin")])

    def test_failed_delivery_is_visible_and_audited(self):
        class BrokenProvider:
            def send_notification(self, notification_id):
                raise RuntimeError("offline")
        match = self._match(2)
        # Existing automatic notification uses the safe provider. A fresh type exercises failure handling.
        NotificationService(self.store, BrokenProvider()).notify_match_event(match["id"], "VERIFIED")
        failed = [item for item in self.store.list_notifications("parent") if item["status"] == "FAILED"]
        self.assertTrue(failed)
        self.assertIn("NOTIFICATION_FAILED", [item["action"] for item in self.store.list_audit_logs("admin")])

    def test_verify_and_reject_create_conservative_parent_updates_and_keep_terminal_rules(self):
        verified = self._match(3)
        self.store.review_match("reviewer", verified["id"], "VERIFY", confirmed=True)
        parent_text = " ".join(item["message"] for item in self.store.list_notifications("parent"))
        self.assertIn("important update", parent_text)
        self.assertNotIn("found", parent_text.lower())
        with self.assertRaisesRegex(ValidationError, "Only a PENDING"):
            self.store.review_match("reviewer", verified["id"], "REJECT", confirmed=True)
        rejected = self._match(4)
        self.store.review_match("reviewer", rejected["id"], "REJECT", "Rejected")
        self.assertTrue(any(item["notification_type"] == "PARENT_REJECTED" for item in self.store.list_notifications("parent")))

    def test_active_assigned_station_and_not_unassigned_station_receive_notification(self):
        self.store.assign_station("hq_police", "CASE001", "LOCAL", "ACTIVE")
        self._match()
        self.assertEqual(self.store.get_authorized_case_stations("CASE001"), ["HQ", "LOCAL"])
        self.assertEqual(len(self.store.list_notifications("local_police")), 1)
        self.assertEqual(self.store.list_notifications("other_police"), [])
        self.assertEqual(len(self.store.list_matches("local_police")), 1)

    def test_closed_station_assignment_cannot_receive_notification(self):
        self.store.assign_station("hq_police", "CASE001", "LOCAL", "CLOSED")
        self._match()
        self.assertEqual(self.store.list_notifications("local_police"), [])

    def test_parent_cannot_modify_station_assignment(self):
        with self.assertRaises(AuthorizationError):
            self.store.assign_station("parent", "CASE001", "LOCAL")

    def test_last_observed_camera_is_not_live_gps_and_is_staff_only(self):
        match = self._match()
        self.store.register_camera("hq_police", {"camera_id": "CAM01", "station_code": "HQ", "camera_name": "North Gate", "location_description": "Gate", "active": True})
        self.store.record_match_observation("hq_police", match["id"], "CAM01", "2026-08-30T10:00:00+00:00")
        context = self.store.notification_match_context(match["id"])
        self.assertEqual(context["last_observed"]["camera_id"], "CAM01")
        self.assertNotIn("gps", context["last_observed"]["camera_name"].lower())
        self.assertNotIn("last_observed", self.store.list_notifications("parent")[0]["message"])

    def test_metadata_rejects_secrets_and_oversized_payload(self):
        with self.assertRaisesRegex(ValidationError, "restricted"):
            NotificationService._metadata({"api_key": "no"})
        with self.assertRaisesRegex(ValidationError, "size"):
            NotificationService._metadata({"note": "x" * 5000})

    def test_invalid_notification_id_and_inactive_user_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.store.mark_notification_read("parent", "not-a-number")
        self.store.deactivate_user("admin", "parent", False)
        with self.assertRaises(AuthorizationError):
            self.store.list_notifications("parent")

    def test_notification_audits_do_not_include_secrets_and_parent_template_is_safe(self):
        self._match()
        details = " ".join(item["details"] or "" for item in self.store.list_audit_logs("admin"))
        self.assertNotIn(PASSWORD, details)
        title, message, _ = parent_template("PENDING", "CASE001")
        self.assertTrue(title)
        self.assertNotIn("score", message.lower())

    def test_migration_preserves_existing_sprint5_data(self):
        path = Path(self.temp.name) / "legacy.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL, station TEXT, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, timestamp TEXT NOT NULL, details TEXT)")
        db.execute("INSERT INTO users(username, role, station, created_at) VALUES ('legacy', 'ADMIN', 'HQ', '2026-01-01T00:00:00+00:00')")
        db.commit(); db.close()
        migrated = ReviewStore(path); migrated.initialize()
        self.assertTrue(migrated.get_user("legacy"))
        with migrated._connection() as db:
            self.assertTrue(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'").fetchone())

    def test_expired_session_is_not_an_authorization_bypass(self):
        session = build_session(self.store.get_user("parent"))
        session["last_seen_at"] = "2000-01-01T00:00:00+00:00"
        self.assertTrue(session_expired(session, 30))

