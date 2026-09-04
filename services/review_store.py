"""SQLite-backed Sprint 4 case and human-review foundation.

This module deliberately stores review decisions separately from AI inference.
It never runs YOLO, DeepSORT, or InsightFace and never promotes a match without
an explicit authorized reviewer action.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

try:
    from .auth import hash_password, iso_now, password_needs_rehash, verify_password
    from .config import ALERTS_DIR, CCTV_UPLOADS_DIR, DATABASE_PATH, LOGIN_LOCKOUT_MINUTES, LOGIN_MAX_FAILURES, MAX_CCTV_UPLOAD_BYTES, safe_filename
except ImportError:
    from auth import hash_password, iso_now, password_needs_rehash, verify_password
    from config import ALERTS_DIR, CCTV_UPLOADS_DIR, DATABASE_PATH, LOGIN_LOCKOUT_MINUTES, LOGIN_MAX_FAILURES, MAX_CCTV_UPLOAD_BYTES, safe_filename


ROLES = {"ADMIN", "POLICE", "REVIEWER", "PARENT"}
CASE_STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "UNDER_REVIEW", "RESOLVED", "CLOSED", "ARCHIVED"}
CASE_STATE_TRANSITIONS = {
    "DRAFT": {"PENDING_POLICE_VERIFICATION", "ACTIVE"},
    "PENDING_POLICE_VERIFICATION": {"ACTIVE"},
    "ACTIVE": {"PAUSED", "UNDER_REVIEW", "CLOSED"}, "PAUSED": {"ACTIVE", "CLOSED"},
    "UNDER_REVIEW": {"ACTIVE", "RESOLVED", "CLOSED"}, "RESOLVED": {"CLOSED"},
    "CLOSED": {"ARCHIVED"}, "ARCHIVED": set(),
}
MATCH_STATUSES = {"PENDING", "VERIFIED", "REJECTED"}
ASSIGNMENT_STATUSES = {"ACTIVE", "PENDING", "CLOSED"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024

ROLE_PERMISSIONS = {
    "ADMIN": {"manage_users", "manage_cases", "review_matches", "view_audit", "submit_cctv"},
    "POLICE": {"manage_cases", "review_matches", "view_internal", "submit_cctv"},
    "REVIEWER": {"review_matches", "view_internal"},
    "PARENT": {"view_own_case", "view_parent_match"},
}


class ValidationError(ValueError):
    """Raised for safe, user-correctable data errors."""


class AuthorizationError(PermissionError):
    """Raised when a local prototype role cannot access a resource."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class ReviewStore:
    """Small repository with explicit validation and per-action audit records."""

    def __init__(self, database_path: Path | str = DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create Sprint 4 tables and indexes idempotently."""
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL CHECK(role IN ('ADMIN','POLICE','REVIEWER','PARENT')),
                    station TEXT, email TEXT, password_hash TEXT, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                    failed_login_count INTEGER NOT NULL DEFAULT 0, lockout_until TEXT, last_login_at TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL UNIQUE, child_id TEXT NOT NULL UNIQUE,
                    child_name TEXT NOT NULL, age INTEGER, description TEXT NOT NULL,
                    reference_image TEXT NOT NULL, case_status TEXT NOT NULL CHECK(case_status IN ('DRAFT','ACTIVE','PAUSED','UNDER_REVIEW','RESOLVED','CLOSED','ARCHIVED')),
                    created_by TEXT NOT NULL, authorized_station TEXT NOT NULL, region TEXT,
                    station_code TEXT, parent_username TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS potential_matches (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id), child_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL, run_id TEXT NOT NULL, frame_number INTEGER NOT NULL,
                    video_name TEXT NOT NULL, face_score REAL, clothing_score REAL, accessory_score REAL,
                    physical_score REAL, overall_score REAL, status TEXT NOT NULL CHECK(status IN ('PENDING','VERIFIED','REJECTED')),
                    evidence_path TEXT, reason TEXT, created_at TEXT NOT NULL, reviewed_at TEXT,
                    reviewed_by TEXT, review_notes TEXT,
                    UNIQUE(case_id, run_id, track_id)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES potential_matches(id) ON DELETE CASCADE,
                    image_path TEXT, metadata_path TEXT, frame_number INTEGER NOT NULL, track_id INTEGER NOT NULL,
                    run_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    evidence_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(evidence_status IN ('ACTIVE','RETENTION_PENDING','EXPIRED','DELETED')),
                    deleted_at TEXT, retention_note TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), role TEXT, action TEXT NOT NULL,
                    resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, timestamp TEXT NOT NULL, details TEXT
                );
                CREATE TABLE IF NOT EXISTS case_station_assignments (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    station_code TEXT NOT NULL, assignment_status TEXT NOT NULL CHECK(assignment_status IN ('ACTIVE','PENDING','CLOSED')),
                    assigned_at TEXT NOT NULL, assigned_by TEXT NOT NULL,
                    UNIQUE(case_id, station_code)
                );
                CREATE TABLE IF NOT EXISTS cameras (
                    id INTEGER PRIMARY KEY, camera_id TEXT NOT NULL UNIQUE, station_code TEXT NOT NULL,
                    camera_name TEXT NOT NULL, latitude REAL, longitude REAL,
                    location_description TEXT, active INTEGER NOT NULL CHECK(active IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS cctv_submissions (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id), station_location TEXT NOT NULL,
                    uploading_user TEXT NOT NULL, stored_name TEXT NOT NULL, capture_datetime TEXT,
                    description TEXT, processing_status TEXT NOT NULL CHECK(processing_status='PENDING_PROCESSING'),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    potential_match_id INTEGER NOT NULL REFERENCES potential_matches(id) ON DELETE CASCADE,
                    recipient_user_id INTEGER NOT NULL REFERENCES users(id),
                    recipient_role TEXT NOT NULL CHECK(recipient_role IN ('ADMIN','POLICE','REVIEWER','PARENT')),
                    notification_type TEXT NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('IN_APP','CONSOLE')),
                    title TEXT NOT NULL, message TEXT NOT NULL, priority TEXT NOT NULL CHECK(priority IN ('LOW','NORMAL','HIGH')),
                    status TEXT NOT NULL CHECK(status IN ('PENDING','SENT','DELIVERED','READ','FAILED','CANCELLED')),
                    created_at TEXT NOT NULL, sent_at TEXT, read_at TEXT, failure_reason TEXT, metadata_json TEXT NOT NULL,
                    UNIQUE(case_id, potential_match_id, recipient_user_id, notification_type)
                );
                CREATE TABLE IF NOT EXISTS match_observations (
                    id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES potential_matches(id) ON DELETE CASCADE,
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id), observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(match_id, camera_id, observed_at)
                );
                CREATE TABLE IF NOT EXISTS server_sessions (
                    id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_activity_at TEXT NOT NULL, revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS child_reference_images (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    uploaded_by TEXT NOT NULL, opaque_reference TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parent_reference_images (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    owner_username TEXT NOT NULL, relationship_label TEXT NOT NULL, opaque_reference TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'ACTIVE', legal_hold INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS age_progression_references (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    source_child_reference_id INTEGER NOT NULL REFERENCES child_reference_images(id), target_age INTEGER NOT NULL,
                    opaque_reference TEXT, provider TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('PENDING_REVIEW','APPROVED','REJECTED','FAILED')),
                    requested_by TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, created_at TEXT NOT NULL, failure_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS child_reference_embeddings (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                    progression_reference_id INTEGER NOT NULL UNIQUE REFERENCES age_progression_references(id) ON DELETE CASCADE,
                    embedding_json TEXT NOT NULL, embedding_source TEXT NOT NULL CHECK(embedding_source IN ('AGE_PROGRESSED_REFERENCE')),
                    created_by TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cases_station ON cases(authorized_station, case_status);
                CREATE INDEX IF NOT EXISTS idx_matches_case_status ON potential_matches(case_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_matches_run ON potential_matches(run_id, track_id);
                CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, resource_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_user_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_notifications_case ON notifications(case_id, potential_match_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_observations_match ON match_observations(match_id, observed_at DESC);
            """)
            self._migrate_schema(db)

    @staticmethod
    def _migrate_schema(db: sqlite3.Connection) -> None:
        """Add Sprint 5 fields while preserving local Sprint 4 databases."""
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        for definition in (
            "email TEXT", "password_hash TEXT", "is_active INTEGER NOT NULL DEFAULT 1",
            "failed_login_count INTEGER NOT NULL DEFAULT 0", "lockout_until TEXT", "last_login_at TEXT",
        ):
            name = definition.split()[0]
            if name not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {definition}")
        audit_columns = {row[1] for row in db.execute("PRAGMA table_info(audit_logs)")}
        if "outcome" not in audit_columns:
            db.execute("ALTER TABLE audit_logs ADD COLUMN outcome TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL")
        evidence_columns = {row[1] for row in db.execute("PRAGMA table_info(evidence)")}
        for definition in ("evidence_status TEXT NOT NULL DEFAULT 'ACTIVE'", "deleted_at TEXT", "retention_note TEXT", "legal_hold INTEGER NOT NULL DEFAULT 0", "retention_expires_at TEXT", "deletion_reason TEXT"):
            if definition.split()[0] not in evidence_columns:
                db.execute(f"ALTER TABLE evidence ADD COLUMN {definition}")
        case_columns = {row[1] for row in db.execute("PRAGMA table_info(cases)")}
        if "state_changed_at" not in case_columns:
            db.execute("ALTER TABLE cases ADD COLUMN state_changed_at TEXT")
        if "lifecycle_state" not in case_columns:
            db.execute("ALTER TABLE cases ADD COLUMN lifecycle_state TEXT")
        for definition in (
            "police_complaint_status TEXT", "police_complaint_number TEXT", "police_complaint_date TEXT",
            "complaint_police_station TEXT", "police_verified_by TEXT", "police_verified_at TEXT",
            "police_verification_notes TEXT", "last_seen_date TEXT", "last_seen_time TEXT", "last_seen_location TEXT",
        ):
            if definition.split()[0] not in case_columns:
                db.execute(f"ALTER TABLE cases ADD COLUMN {definition}")
        for definition in ("mfa_secret_encrypted TEXT", "mfa_enabled INTEGER NOT NULL DEFAULT 0", "mfa_failed_count INTEGER NOT NULL DEFAULT 0", "mfa_locked_until TEXT"):
            if definition.split()[0] not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {definition}")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_expiry ON server_sessions(user_id, expires_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_parent_references_case ON parent_reference_images(case_id, status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_progression_case_status ON age_progression_references(case_id, status)")

        # Fix outdated CHECK constraint on cases.case_status that only allows
        # ('ACTIVE','PAUSED','CLOSED') but the service logic uses DRAFT,
        # PENDING_POLICE_VERIFICATION, UNDER_REVIEW, RESOLVED, ARCHIVED.
        # SQLite doesn't support ALTER TABLE to modify CHECK constraints, so we
        # recreate the table with the correct constraint when needed.
        ReviewStore._fix_cases_check_constraint(db)



    @staticmethod
    def _fix_cases_check_constraint(db: sqlite3.Connection) -> None:
        """Recreate cases table with correct CHECK constraint if the current one is outdated."""
        # Check current CHECK constraint on case_status
        sql = "SELECT sql FROM sqlite_master WHERE type='table' AND name='cases'"
        row = db.execute(sql).fetchone()
        if not row:
            return
        create_sql = row[0]
        # The correct constraint should include all CASE_STATUSES values
        expected_constraint = "CHECK(case_status IN ('DRAFT','ACTIVE','PAUSED','UNDER_REVIEW','RESOLVED','CLOSED','ARCHIVED'))"
        if expected_constraint in create_sql:
            return  # Already correct
    
        # Recreate table with correct CHECK constraint, handling foreign keys
        db.executescript("""
            PRAGMA foreign_keys = OFF;
            CREATE TABLE cases_new (
                id INTEGER PRIMARY KEY, case_id TEXT NOT NULL UNIQUE, child_id TEXT NOT NULL UNIQUE,
                child_name TEXT NOT NULL, age INTEGER, description TEXT NOT NULL,
                reference_image TEXT NOT NULL, case_status TEXT NOT NULL CHECK(case_status IN ('DRAFT','ACTIVE','PAUSED','UNDER_REVIEW','RESOLVED','CLOSED','ARCHIVED')),
                created_by TEXT NOT NULL, authorized_station TEXT NOT NULL, region TEXT,
                station_code TEXT, parent_username TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                state_changed_at TEXT, lifecycle_state TEXT, police_complaint_status TEXT,
                police_complaint_number TEXT, police_complaint_date TEXT, complaint_police_station TEXT,
                police_verified_by TEXT, police_verified_at TEXT, police_verification_notes TEXT,
                last_seen_date TEXT, last_seen_time TEXT, last_seen_location TEXT
            );
            INSERT INTO cases_new SELECT * FROM cases;
            DROP TABLE cases;
            ALTER TABLE cases_new RENAME TO cases;
            CREATE INDEX idx_cases_station ON cases(authorized_station, case_status);
            PRAGMA foreign_keys = ON;
        """)
    
    
        def create_user(self, username: str, role: str, station: str | None = None, password: str | None = None, email: str | None = None, actor: str | None = None) -> dict[str, Any]:
            """Create a user; callers should pass an ADMIN actor outside bootstrap/tests."""
            self.initialize()
            administrator = self._require(actor, "manage_users") if actor else None
            username = self._identifier(username, "username")
            if role not in ROLES:
                raise ValidationError("Role must be ADMIN, POLICE, REVIEWER, or PARENT.")
            normalized_email = self._email(email) if email else None
            password_hash = hash_password(password) if password is not None else None
            with self._connection() as db:
                try:
                    db.execute("INSERT INTO users(username, role, station, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)", (username, role, station, normalized_email, password_hash, _now()))
                except sqlite3.IntegrityError as exc:
                    raise ValidationError("Username or email already exists.") from exc
            created = self.get_user(username)
            if administrator and created:
                self._audit(administrator, "USER_CREATED", "user", str(created["id"]), {"role": role, "station": station})
            return created  # type: ignore[return-value]
    
        def get_user(self, username: str) -> dict[str, Any] | None:
            with self._connection() as db:
                return _row(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
    
        def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
            with self._connection() as db:
                return _row(db.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())
    
        def user_count(self) -> int:
            with self._connection() as db:
                return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    
        def credentialed_active_user_count(self) -> int:
            """Count accounts that can actually use the Sprint 5 login flow."""
            with self._connection() as db:
                return int(db.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND password_hash IS NOT NULL").fetchone()[0])
    
        def bootstrap_admin(self, username: str, email: str, password: str) -> dict[str, Any]:
            """Create the first admin only when the database has no users."""
            if self.credentialed_active_user_count():
                existing = self.get_user(username)
                if not existing:
                    raise AuthorizationError("An administrator already exists; use an authenticated admin to create users.")
                return existing
            existing = self.get_user(username)
            if existing:
                with self._connection() as db:
                    db.execute("UPDATE users SET role='ADMIN', email=?, password_hash=?, is_active=1, failed_login_count=0, lockout_until=NULL WHERE id=?", (self._email(email), hash_password(password), existing["id"]))
                return self.get_user(username)  # type: ignore[return-value]
            return self.create_user(username, "ADMIN", station="HQ", password=password, email=email)
    
        def authenticate(self, username_or_email: str, password: str) -> dict[str, Any] | None:
            """Return an active user only after rate-limit and Argon2 verification."""
            self.initialize()
            identity = str(username_or_email).strip().lower()
            with self._connection() as db:
                user = _row(db.execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?", (identity, identity)).fetchone())
                if not user or not user.get("is_active") or self._locked(user):
                    self._audit_login_failure(db, user, identity)
                    return None
                if not verify_password(user.get("password_hash"), password):
                    self._audit_login_failure(db, user, identity)
                    return None
                replacement_hash = hash_password(password) if password_needs_rehash(user.get("password_hash")) else user.get("password_hash")
                db.execute("UPDATE users SET failed_login_count=0, lockout_until=NULL, last_login_at=?, password_hash=? WHERE id=?", (iso_now(), replacement_hash, user["id"]))
                authenticated = _row(db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
            self._audit(authenticated, "LOGIN_SUCCESS", "user", str(authenticated["id"]), {"outcome": "success"})
            return authenticated
    
        def record_logout(self, user_id: int) -> None:
            user = self._active_user_by_id(user_id)
            self._audit(user, "LOGOUT", "user", str(user["id"]), {"outcome": "success"})
    
        def deactivate_user(self, actor: str, username: str, active: bool) -> dict[str, Any]:
            administrator = self._require(actor, "manage_users")
            target = self.get_user(username)
            if not target:
                raise ValidationError("User does not exist.")
            with self._connection() as db:
                db.execute("UPDATE users SET is_active=? WHERE id=?", (int(active), target["id"]))
            result = self.get_user(username)
            self._audit(administrator, "USER_ACTIVATED" if active else "USER_DEACTIVATED", "user", str(target["id"]), {})
            return result  # type: ignore[return-value]
    
        def change_user_role(self, actor: str, username: str, role: str) -> dict[str, Any]:
            administrator = self._require(actor, "manage_users")
            if role not in ROLES:
                raise ValidationError("Role must be ADMIN, POLICE, REVIEWER, or PARENT.")
            target = self.get_user(username)
            if not target:
                raise ValidationError("User does not exist.")
            with self._connection() as db:
                db.execute("UPDATE users SET role=? WHERE id=?", (role, target["id"]))
            result = self.get_user(username)
            self._audit(administrator, "USER_ROLE_CHANGED", "user", str(target["id"]), {"role": role})
            return result  # type: ignore[return-value]
    
        def change_password(self, actor: str, current_password: str, new_password: str) -> None:
            """Authenticated password change; Argon2 and minimum-length policy remain central."""
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
            if not verify_password(user.get("password_hash"), current_password):
                self._audit(user, "PASSWORD_CHANGE_FAILURE", "user", str(user["id"]), {}, "FAILURE")
                raise AuthorizationError("Current credentials could not be verified.")
            replacement = hash_password(new_password)
            with self._connection() as db:
                db.execute("UPDATE users SET password_hash=?, failed_login_count=0, lockout_until=NULL WHERE id=?", (replacement, user["id"]))
            self._audit(user, "PASSWORD_CHANGED", "user", str(user["id"]), {})
    
        def admin_reset_password(self, actor: str, username: str, new_password: str, reason: str) -> None:
            administrator = self._require(actor, "manage_users")
            target = self.get_user(username)
            if not target or not reason.strip():
                raise ValidationError("A target user and reset reason are required.")
            with self._connection() as db:
                db.execute("UPDATE users SET password_hash=?, failed_login_count=0, lockout_until=NULL WHERE id=?", (hash_password(new_password), target["id"]))
            self._audit(administrator, "PASSWORD_RESET_ADMIN_ASSISTED", "user", str(target["id"]), {"reason": reason.strip()[:300]})
    
        def record_login(self, actor: str) -> None:
            """Audit a local demo identity selection; this is not authentication."""
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
            self._audit(user, "LOGIN", "user", str(user["id"]), {"prototype": True})
    
        def create_case(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
            user = self._require(actor, "manage_cases")
            case = self._validate_case(data)
            timestamp = _now()
            with self._connection() as db:
                try:
                    db.execute("""INSERT INTO cases(case_id, child_id, child_name, age, description, reference_image,
                        case_status, created_by, authorized_station, region, station_code, parent_username, created_at, updated_at)
                        VALUES (:case_id, :child_id, :child_name, :age, :description, :reference_image, :case_status,
                        :created_by, :authorized_station, :region, :station_code, :parent_username, :created_at, :updated_at)""",
                        {**case, "created_by": actor, "created_at": timestamp, "updated_at": timestamp})
                except sqlite3.IntegrityError as exc:
                    raise ValidationError("Case ID or child ID already exists.") from exc
            created = self.get_case(actor, case["case_id"])
            self._audit(user, "CASE_CREATED", "case", case["case_id"], {"station": case["authorized_station"]})
            return created  # type: ignore[return-value]
    
        def create_preliminary_report(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
            """Let a parent submit a report without activating an investigation."""
            parent = self._require(actor, "view_own_case")
            if parent["role"] != "PARENT":
                raise AuthorizationError("Preliminary reports are submitted by the reporting parent or guardian.")
            case = self._validate_case({**data, "case_status": "DRAFT", "parent_username": actor})
            timestamp = _now()
            with self._connection() as db:
                try:
                    db.execute("""INSERT INTO cases(case_id, child_id, child_name, age, description, reference_image, case_status,
                        lifecycle_state, created_by, authorized_station, region, station_code, parent_username, last_seen_date,
                        last_seen_time, last_seen_location, police_complaint_status, police_complaint_number,
                        police_complaint_date, complaint_police_station, created_at, updated_at)
                        VALUES (:case_id, :child_id, :child_name, :age, :description, :reference_image, 'DRAFT',
                        'PENDING_POLICE_VERIFICATION', :created_by, :authorized_station, :region, :station_code, :parent_username,
                        :last_seen_date, :last_seen_time, :last_seen_location, 'AWAITING_VERIFICATION', :police_complaint_number,
                        :police_complaint_date, :complaint_police_station, :created_at, :updated_at)""",
                        {**case, "created_by": actor, "last_seen_date": str(data.get("last_seen_date", "")).strip() or None,
                         "last_seen_time": str(data.get("last_seen_time", "")).strip() or None,
                         "last_seen_location": str(data.get("last_seen_location", "")).strip() or None,
                         "police_complaint_number": self._identifier(str(data.get("police_complaint_number", "UNVERIFIED")), "complaint reference"),
                         "police_complaint_date": str(data.get("police_complaint_date", "")).strip() or None,
                         "complaint_police_station": str(data.get("complaint_police_station", case["authorized_station"])).strip()[:120],
                         "created_at": timestamp, "updated_at": timestamp})
                except sqlite3.IntegrityError as exc:
                    raise ValidationError("Case ID or child ID already exists.") from exc
            created = self.get_case(actor, case["case_id"])
            self._audit(parent, "PRELIMINARY_REPORT_CREATED", "case", case["case_id"], {"status": "PENDING_POLICE_VERIFICATION"})
            return created  # type: ignore[return-value]
    
        def verify_police_complaint(self, actor: str, case_id: str, complaint_number: str, complaint_date: str,
                                    police_station: str, notes: str = "") -> dict[str, Any]:
            """Police/admin approval is the only path from an intake report to ACTIVE."""
            officer = self._require(actor, "manage_cases")
            case = self._case_for(case_id)
            if not case:
                raise ValidationError("Case does not exist.")
            self._assert_case_access(officer, case)
            if (case.get("lifecycle_state") or case["case_status"]) != "PENDING_POLICE_VERIFICATION":
                raise ValidationError("Only reports awaiting police verification can be activated.")
            complaint_number = self._identifier(complaint_number, "complaint reference")
            if not complaint_date.strip() or not police_station.strip():
                raise ValidationError("Complaint date and police station are required for verification.")
            with self._connection() as db:
                db.execute("""UPDATE cases SET case_status='ACTIVE', lifecycle_state='ACTIVE', state_changed_at=?, updated_at=?,
                    police_complaint_status='VERIFIED', police_complaint_number=?, police_complaint_date=?,
                    complaint_police_station=?, police_verified_by=?, police_verified_at=?, police_verification_notes=? WHERE case_id=?""",
                    (_now(), _now(), complaint_number, complaint_date.strip()[:40], police_station.strip()[:120], actor, _now(), notes.strip()[:500], case_id))
            result = self.get_case(actor, case_id)
            self._audit(officer, "POLICE_COMPLAINT_VERIFIED", "case", case_id, {"from": "PENDING_POLICE_VERIFICATION", "to": "ACTIVE"})
            return result  # type: ignore[return-value]
    
        def case_allows_ai_processing(self, case_id: str) -> bool:
            """Explicit gate: legacy active cases work; unverified intake reports do not."""
            case = self._case_for(case_id)
            return bool(case and (case.get("lifecycle_state") or case.get("case_status")) == "ACTIVE")
    
        def _reference_access(self, actor: str, case_id: str, owner_only: bool = False) -> dict[str, Any]:
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches"})
            case = self._case_for(case_id)
            if not case:
                raise ValidationError("Case does not exist.")
            self._assert_case_access(user, case)
            if owner_only and case.get("parent_username") != actor:
                raise AuthorizationError("Only the reporting parent or guardian may manage this reference.")
            return user
    
        def add_child_reference(self, actor: str, case_id: str, filename: str, opaque_reference: str) -> dict[str, Any]:
            user = self._reference_access(actor, case_id, owner_only=self.get_user(actor).get("role") == "PARENT")  # type: ignore[union-attr]
            self._safe_media_name(filename, IMAGE_EXTENSIONS)
            reference = self._safe_evidence_path(opaque_reference) or ""
            if not reference.endswith(".fernet"):
                raise ValidationError("Child references require controlled encrypted storage.")
            with self._connection() as db:
                cursor = db.execute("INSERT INTO child_reference_images(case_id, uploaded_by, opaque_reference, created_at) VALUES (?, ?, ?, ?)", (case_id, actor, reference, _now()))
                row = _row(db.execute("SELECT * FROM child_reference_images WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "CHILD_REFERENCE_UPLOADED", "child_reference", str(row["id"]), {"case_id": case_id})
            return row  # type: ignore[return-value]
    
        def add_parent_reference(self, actor: str, case_id: str, relationship_label: str, filename: str, opaque_reference: str) -> dict[str, Any]:
            user = self._reference_access(actor, case_id, owner_only=True)
            self._safe_media_name(filename, IMAGE_EXTENSIONS)
            reference = self._safe_evidence_path(opaque_reference) or ""
            if not reference.endswith(".fernet") or not relationship_label.strip():
                raise ValidationError("A relationship label and controlled encrypted reference are required.")
            with self._connection() as db:
                cursor = db.execute("INSERT INTO parent_reference_images(case_id, owner_username, relationship_label, opaque_reference, created_at) VALUES (?, ?, ?, ?, ?)", (case_id, actor, relationship_label.strip()[:80], reference, _now()))
                row = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "PARENT_REFERENCE_UPLOADED", "parent_reference", str(row["id"]), {"case_id": case_id, "relationship": relationship_label.strip()[:80]})
            return row  # type: ignore[return-value]
    
        def list_parent_references(self, actor: str, case_id: str) -> list[dict[str, Any]]:
            user = self._reference_access(actor, case_id)
            with self._connection() as db:
                rows = [_row(row) for row in db.execute("SELECT id, case_id, relationship_label, status, created_at FROM parent_reference_images WHERE case_id=? AND status='ACTIVE'", (case_id,))]
            self._audit(user, "PARENT_REFERENCE_LIST_VIEWED", "case", case_id, {})
            return [row for row in rows if row]
    
        def list_age_progression_references(self, actor: str, case_id: str) -> list[dict[str, Any]]:
            user = self._reference_access(actor, case_id)
            with self._connection() as db:
                rows = [_row(row) for row in db.execute("SELECT id, case_id, target_age, provider, status, created_at, reviewed_at FROM age_progression_references WHERE case_id=? ORDER BY created_at DESC", (case_id,))]
            self._audit(user, "AGE_PROGRESSION_LIST_VIEWED", "case", case_id, {})
            return [row for row in rows if row]
    
        def list_pending_age_progression_references(self, actor: str) -> list[dict[str, Any]]:
            user = self._require(actor, "review_matches")
            with self._connection() as db:
                rows = [_row(row) for row in db.execute("SELECT id, case_id, target_age, provider, status, created_at FROM age_progression_references WHERE status='PENDING_REVIEW' ORDER BY created_at ASC")]
            return [row for row in rows if row and self._case_allowed(user, self._case_for(row["case_id"]) or {})]
    
        def delete_parent_reference(self, actor: str, reference_id: int, reason: str, explicitly_confirmed: bool = False) -> None:
            if not explicitly_confirmed or not reason.strip():
                raise ValidationError("Explicit confirmation and a reason are required to delete a parent reference.")
            with self._connection() as db:
                reference = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (int(reference_id),)).fetchone())
                if not reference:
                    raise ValidationError("Parent reference does not exist.")
                user = self._reference_access(actor, reference["case_id"], owner_only=True)
                if reference.get("legal_hold"):
                    raise AuthorizationError("A reference under legal hold cannot be deleted.")
                db.execute("UPDATE parent_reference_images SET status='DELETED', deleted_at=? WHERE id=?", (_now(), reference_id))
            self._audit(user, "PARENT_REFERENCE_DELETED", "parent_reference", str(reference_id), {"case_id": reference["case_id"], "logical": True})
    
        def set_parent_reference_legal_hold(self, actor: str, reference_id: int, enabled: bool, reason: str) -> None:
            admin = self._require(actor, "manage_users")
            if not reason.strip():
                raise ValidationError("A legal-hold reason is required.")
            with self._connection() as db:
                reference = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (int(reference_id),)).fetchone())
                if not reference:
                    raise ValidationError("Parent reference does not exist.")
                db.execute("UPDATE parent_reference_images SET legal_hold=? WHERE id=?", (int(enabled), reference_id))
            self._audit(admin, "PARENT_REFERENCE_LEGAL_HOLD_SET" if enabled else "PARENT_REFERENCE_LEGAL_HOLD_RELEASED", "parent_reference", str(reference_id), {"case_id": reference["case_id"]})
    
        def create_age_progression_reference(self, actor: str, case_id: str, child_reference_id: int, target_age: int,
                                             provider: str, opaque_reference: str | None) -> dict[str, Any]:
            user = self._reference_access(actor, case_id)
            case = self._case_for(case_id) or {}
            if not isinstance(target_age, int) or isinstance(target_age, bool) or target_age < int(case.get("age") or 0) or target_age > 120:
                raise ValidationError("Target age must be a valid age at or above the child's recorded age.")
            with self._connection() as db:
                source = _row(db.execute("SELECT * FROM child_reference_images WHERE id=? AND case_id=? AND status='ACTIVE'", (int(child_reference_id), case_id)).fetchone())
                if not source:
                    raise ValidationError("An active controlled child reference is required.")
                cursor = db.execute("INSERT INTO age_progression_references(case_id, source_child_reference_id, target_age, opaque_reference, provider, status, requested_by, created_at) VALUES (?, ?, ?, ?, ?, 'PENDING_REVIEW', ?, ?)", (case_id, child_reference_id, target_age, self._safe_evidence_path(opaque_reference) if opaque_reference else None, provider[:120], actor, _now()))
                row = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "AGE_PROGRESSION_GENERATED", "age_progression_reference", str(row["id"]), {"case_id": case_id, "target_age": target_age, "status": "PENDING_REVIEW", "provider": provider[:120]})
            return row  # type: ignore[return-value]
    
        def review_age_progression_reference(self, actor: str, reference_id: int, approve: bool) -> dict[str, Any]:
            reviewer = self._require(actor, "review_matches")
            with self._connection() as db:
                reference = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
                if not reference:
                    raise ValidationError("Age-progression reference does not exist.")
                self._assert_case_access(reviewer, self._case_for(reference["case_id"]) or {})
                if reference["status"] != "PENDING_REVIEW":
                    raise ValidationError("Only a PENDING_REVIEW age-progression reference may be reviewed.")
                status = "APPROVED" if approve else "REJECTED"
                db.execute("UPDATE age_progression_references SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?", (status, actor, _now(), reference_id))
                result = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (reference_id,)).fetchone())
            self._audit(reviewer, "AGE_PROGRESSION_APPROVED" if approve else "AGE_PROGRESSION_REJECTED", "age_progression_reference", str(reference_id), {"case_id": reference["case_id"]})
            return result  # type: ignore[return-value]
    
        def attach_age_progression_output(self, reference_id: int, opaque_reference: str) -> None:
            """System boundary for a provider result; no user-supplied paths are accepted."""
            reference = self._safe_evidence_path(opaque_reference) or ""
            if not reference.endswith(".fernet"):
                raise ValidationError("Generated reference requires controlled encrypted storage.")
            with self._connection() as db:
                if not db.execute("SELECT id FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone():
                    raise ValidationError("Age-progression reference does not exist.")
                db.execute("UPDATE age_progression_references SET opaque_reference=? WHERE id=?", (reference, reference_id))
    
        def _row_for_progression(self, reference_id: int) -> dict[str, Any]:
            with self._connection() as db:
                row = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
            if not row:
                raise ValidationError("Age-progression reference does not exist.")
            return row
    
        def add_age_progression_embedding(self, actor: str, reference_id: int, embedding: list[float]) -> dict[str, Any]:
            user = self._require(actor, "review_matches")
            if not isinstance(embedding, list) or not embedding or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in embedding):
                raise ValidationError("Embedding must contain finite numeric values.")
            with self._connection() as db:
                reference = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
                if not reference or reference["status"] != "APPROVED":
                    raise ValidationError("Only an approved age-progression reference may become a matching reference.")
                self._assert_case_access(user, self._case_for(reference["case_id"]) or {})
                cursor = db.execute("INSERT INTO child_reference_embeddings(case_id, progression_reference_id, embedding_json, embedding_source, created_by, created_at) VALUES (?, ?, ?, 'AGE_PROGRESSED_REFERENCE', ?, ?)", (reference["case_id"], reference_id, json.dumps(embedding), actor, _now()))
                row = _row(db.execute("SELECT * FROM child_reference_embeddings WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "AGE_PROGRESSION_EMBEDDING_CREATED", "child_reference_embedding", str(row["id"]), {"case_id": reference["case_id"], "source": "AGE_PROGRESSED_REFERENCE"})
            return row  # type: ignore[return-value]
    
        def get_case(self, actor: str, case_id: str) -> dict[str, Any] | None:
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases"})
            with self._connection() as db:
                case = _row(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone())
            if not case:
                return None
            self._assert_case_access(user, case)
            return self._parent_safe_case(case) if user["role"] == "PARENT" else case
    
        def get_case_for_user(self, user_id: int, case_id: str) -> dict[str, Any] | None:
            """Authenticated-ID variant used by the dashboard session boundary."""
            user = self._active_user_by_id(user_id)
            return self.get_case(user["username"], case_id)
    
        def update_case(self, actor: str, case_id: str, updates: dict[str, Any]) -> dict[str, Any]:
            """Allow only police/admin case-state updates and preserve safe fields."""
            user = self._require(actor, "manage_cases")
            existing = self._case_for(case_id)
            if not existing:
                raise ValidationError("Case does not exist.")
            self._assert_case_access(user, existing)
            allowed = {"child_name", "age", "description", "reference_image", "case_status", "authorized_station", "region", "station_code", "parent_username"}
            merged = {**existing, **{key: value for key, value in updates.items() if key in allowed}}
            validated = self._validate_case(merged)
            with self._connection() as db:
                db.execute("""UPDATE cases SET child_name=:child_name, age=:age, description=:description,
                    reference_image=:reference_image, case_status=:case_status, authorized_station=:authorized_station,
                    region=:region, station_code=:station_code, parent_username=:parent_username, updated_at=:updated_at
                    WHERE case_id=:case_id""", {**validated, "updated_at": _now()})
            result = self.get_case(actor, case_id)
            self._audit(user, "CASE_UPDATED", "case", case_id, {"fields": sorted(set(updates).intersection(allowed))})
            return result  # type: ignore[return-value]
    
        def transition_case_state(self, actor: str, case_id: str, target: str, reason: str = "") -> dict[str, Any]:
            """Perform an explicitly allowed, audited case lifecycle transition."""
            user = self._require(actor, "manage_cases")
            case = self._case_for(case_id)
            if not case:
                raise ValidationError("Case does not exist.")
            self._assert_case_access(user, case)
            source = case.get("lifecycle_state") or case["case_status"]
            if target not in CASE_STATE_TRANSITIONS.get(source, set()):
                raise ValidationError(f"Case cannot transition from {source} to {target}.")
            with self._connection() as db:
                # Keep legacy case_status compatible with prior SQLite CHECK constraints;
                # lifecycle_state carries the richer Sprint 7 state machine.
                legacy_status = "CLOSED" if target in {"CLOSED", "ARCHIVED"} else "DRAFT" if target in {"DRAFT", "PENDING_POLICE_VERIFICATION"} else "ACTIVE"
                db.execute("UPDATE cases SET case_status=?, lifecycle_state=?, updated_at=?, state_changed_at=? WHERE case_id=?", (legacy_status, target, _now(), _now(), case_id))
            result = self.get_case(actor, case_id)
            self._audit(user, "CASE_CLOSED" if target == "CLOSED" else "CASE_STATE_CHANGED", "case", case_id, {"from": source, "to": target, "reason": reason.strip()[:300]})
            return result  # type: ignore[return-value]
    
        def list_cases(self, actor: str) -> list[dict[str, Any]]:
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases"})
            with self._connection() as db:
                rows = [_row(row) for row in db.execute("SELECT * FROM cases ORDER BY updated_at DESC")]
            allowed = [case for case in rows if case and self._case_allowed(user, case)]
            return [self._parent_safe_case(case) if user["role"] == "PARENT" else case for case in allowed]
    
        def list_cases_for_user(self, user_id: int) -> list[dict[str, Any]]:
            return self.list_cases(self._active_user_by_id(user_id)["username"])
    
        def record_potential_match(self, data: dict[str, Any]) -> dict[str, Any]:
            """Store an AI result as PENDING; only review_match can change it."""
            self.initialize()
            required = {"case_id", "child_id", "track_id", "run_id", "frame_number", "video_name"}
            if missing := required - data.keys():
                raise ValidationError(f"Potential match is missing: {', '.join(sorted(missing))}")
            if data.get("status", "PENDING") != "PENDING":
                raise ValidationError("New AI potential matches must start as PENDING.")
            self._safe_media_name(str(data["video_name"]), VIDEO_EXTENSIONS)
            with self._connection() as db:
                case = db.execute("SELECT case_id, child_id, case_status, lifecycle_state FROM cases WHERE case_id = ?", (data["case_id"],)).fetchone()
                if not case or case["child_id"] != data["child_id"]:
                    raise ValidationError("Potential match must reference its existing case and child ID.")
                if (case["lifecycle_state"] or case["case_status"]) != "ACTIVE":
                    self._audit_system("POTENTIAL_MATCH_BLOCKED_CASE_NOT_ACTIVE", "case", data["case_id"], {"status": case["lifecycle_state"] or case["case_status"]})
                    raise AuthorizationError("AI potential matches are blocked until the case is ACTIVE.")
                try:
                    cursor = db.execute("""INSERT INTO potential_matches(case_id, child_id, track_id, run_id, frame_number, video_name,
                        face_score, clothing_score, accessory_score, physical_score, overall_score, status, evidence_path, reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)""",
                        (data["case_id"], data["child_id"], int(data["track_id"]), str(data["run_id"]), int(data["frame_number"]),
                         data["video_name"], data.get("face_score"), data.get("clothing_score"), data.get("accessory_score"),
                         data.get("physical_score", data.get("physical_feature_score")), data.get("overall_score"),
                         self._safe_evidence_path(data.get("evidence_path")), self._json_text(data.get("reason", data.get("evidence_reasons", {}))), _now()))
                except sqlite3.IntegrityError as exc:
                    raise ValidationError("A potential match for this case, run, and track already exists.") from exc
                match_id = cursor.lastrowid
                if data.get("evidence_path") or data.get("metadata_path"):
                    db.execute("INSERT INTO evidence(match_id, image_path, metadata_path, frame_number, track_id, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (match_id, self._safe_evidence_path(data.get("evidence_path")), self._safe_evidence_path(data.get("metadata_path")), int(data["frame_number"]), int(data["track_id"]), str(data["run_id"]), _now()))
                row = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
            self._audit_system("POTENTIAL_MATCH_CREATED", "potential_match", str(match_id), {"case_id": data["case_id"], "run_id": str(data["run_id"]), "status": "PENDING"})
            self._dispatch_notification_event(match_id, "PENDING")
            return row  # type: ignore[return-value]
    
        def record_pipeline_match_for_child(self, data: dict[str, Any]) -> dict[str, Any] | None:
            """Bridge a pipeline event into the review store only when a managed case exists.
    
            A matcher event without a case record remains an existing local evidence event;
            it is never converted into a public notification.
            """
            child_id = self._identifier(str(data.get("child_id", "")), "child ID")
            with self._connection() as db:
                case = _row(db.execute("SELECT case_id FROM cases WHERE child_id=?", (child_id,)).fetchone())
            if not case:
                return None
            if not self.case_allows_ai_processing(case["case_id"]):
                self._audit_system("PIPELINE_MATCH_BLOCKED_CASE_NOT_ACTIVE", "case", case["case_id"], {"child_id": child_id})
                return None
            return self.record_potential_match({
                "case_id": case["case_id"], "child_id": child_id, "track_id": data["track_id"], "run_id": data["run_id"],
                "frame_number": data["frame_number"], "video_name": data["cctv_source"], "face_score": data.get("face_score"),
                "clothing_score": data.get("clothing_score"), "accessory_score": data.get("accessory_score"),
                "physical_feature_score": data.get("physical_feature_score"), "overall_score": data.get("overall_score"),
                "reason": data.get("evidence_reasons", {}), "evidence_path": Path(str(data.get("evidence_image", ""))).name,
                "metadata_path": Path(str(data.get("evidence_metadata", ""))).name,
            })
    
        def review_match(self, actor: str, match_id: int, action: str, notes: str = "", confirmed: bool = False) -> dict[str, Any]:
            user = self._require(actor, "review_matches")
            action_map = {"KEEP_PENDING": "PENDING", "VERIFY": "VERIFIED", "REJECT": "REJECTED"}
            if action not in action_map:
                raise ValidationError("Review action must be KEEP_PENDING, VERIFY, or REJECT.")
            if action == "VERIFY" and not confirmed:
                raise ValidationError("VERIFY requires explicit confirmation.")
            with self._connection() as db:
                match = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
                if not match:
                    raise ValidationError("Potential match does not exist.")
                case = _row(db.execute("SELECT * FROM cases WHERE case_id = ?", (match["case_id"],)).fetchone())
                self._assert_case_access(user, case or {})
                if match["status"] != "PENDING":
                    raise ValidationError("Only a PENDING potential match may be reviewed. Terminal decisions are preserved.")
                status = action_map[action]
                db.execute("UPDATE potential_matches SET status = ?, reviewed_at = ?, reviewed_by = ?, review_notes = ? WHERE id = ?",
                    (status, _now(), actor, notes.strip(), match_id))
                result = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
            self._audit(user, {"VERIFY": "MATCH_VERIFIED", "REJECT": "MATCH_REJECTED", "KEEP_PENDING": "MATCH_REMAINED_PENDING"}[action], "potential_match", str(match_id), {"from": match["status"], "to": status})
            if action in {"VERIFY", "REJECT"}:
                self._dispatch_notification_event(match_id, status)
            return result  # type: ignore[return-value]
    
        def list_matches(self, actor: str, case_id: str | None = None) -> list[dict[str, Any]]:
            user = self._require(actor, "view_parent_match", allow_any={"view_internal", "manage_cases", "review_matches"})
            query = "SELECT m.* FROM potential_matches m JOIN cases c ON c.case_id=m.case_id"
            params: list[Any] = []
            if case_id:
                query += " WHERE m.case_id = ?"
                params.append(case_id)
            query += " ORDER BY m.created_at DESC"
            with self._connection() as db:
                matches = [_row(row) for row in db.execute(query, params)]
            result = []
            for match in matches:
                if not match:
                    continue
                case = self._case_for(match["case_id"])
                if case and self._case_allowed(user, case):
                    result.append(self._parent_safe_match(match) if user["role"] == "PARENT" else match)
            return result
    
        def list_matches_for_user(self, user_id: int, case_id: str | None = None) -> list[dict[str, Any]]:
            return self.list_matches(self._active_user_by_id(user_id)["username"], case_id)
    
        def get_evidence(self, actor: str, match_id: int) -> dict[str, Any] | None:
            user = self._require(actor, "view_internal", allow_any={"manage_cases", "review_matches"})
            with self._connection() as db:
                evidence = _row(db.execute("SELECT e.*, m.case_id FROM evidence e JOIN potential_matches m ON m.id=e.match_id WHERE e.match_id = ?", (match_id,)).fetchone())
            if evidence:
                case = self._case_for(evidence["case_id"])
                self._assert_case_access(user, case or {})
                self._audit(user, "EVIDENCE_VIEWED", "evidence", str(evidence["id"]), {"case_id": evidence["case_id"], "match_id": match_id})
            return evidence
    
        def mark_evidence_deleted(self, actor: str, evidence_id: int, reason: str, explicitly_confirmed: bool = False) -> None:
            """Controlled logical deletion; never deletes files automatically."""
            administrator = self._require(actor, "manage_users")
            if not explicitly_confirmed or not reason.strip():
                raise ValidationError("Explicit confirmation and a reason are required to delete evidence.")
            with self._connection() as db:
                evidence = _row(db.execute("SELECT e.*, m.case_id FROM evidence e JOIN potential_matches m ON m.id=e.match_id WHERE e.id=?", (int(evidence_id),)).fetchone())
                if not evidence:
                    raise ValidationError("Evidence does not exist.")
                if evidence.get("legal_hold"):
                    raise AuthorizationError("Evidence under legal hold cannot be deleted.")
                db.execute("UPDATE evidence SET evidence_status='DELETED', deleted_at=?, retention_note=?, deletion_reason=? WHERE id=?", (_now(), reason.strip()[:300], reason.strip()[:300], evidence_id))
            self._audit(administrator, "EVIDENCE_DELETED", "evidence", str(evidence_id), {"case_id": evidence["case_id"], "logical": True})
    
        def set_evidence_legal_hold(self, actor: str, evidence_id: int, enabled: bool, reason: str) -> None:
            admin = self._require(actor, "manage_users")
            if not reason.strip(): raise ValidationError("A legal-hold reason is required.")
            with self._connection() as db:
                if not db.execute("SELECT id FROM evidence WHERE id=?", (int(evidence_id),)).fetchone(): raise ValidationError("Evidence does not exist.")
                db.execute("UPDATE evidence SET legal_hold=?, retention_note=? WHERE id=?", (int(enabled), reason.strip()[:300], evidence_id))
            self._audit(admin, "EVIDENCE_LEGAL_HOLD_SET" if enabled else "EVIDENCE_LEGAL_HOLD_RELEASED", "evidence", str(evidence_id), {})
    
        def get_evidence_for_user(self, user_id: int, match_id: int) -> dict[str, Any] | None:
            return self.get_evidence(self._active_user_by_id(user_id)["username"], match_id)
    
        def evidence_display_path(self, actor: str, match_id: int) -> Path | None:
            """Resolve evidence only from the controlled alerts directory, never user input."""
            evidence = self.get_evidence(actor, match_id)
            if not evidence or not evidence.get("image_path"):
                return None
            name = self._safe_media_name(evidence["image_path"], IMAGE_EXTENSIONS)
            candidate = ALERTS_DIR / name
            return candidate if candidate.is_file() else None
    
        def set_encrypted_evidence_reference(self, match_id: int, reference: str) -> None:
            """System-only bridge for a newly encrypted controlled evidence file."""
            reference = self._safe_evidence_path(reference) or ""
            if not reference.endswith(".fernet"):
                raise ValidationError("Encrypted evidence reference is invalid.")
            with self._connection() as db:
                evidence = _row(db.execute("SELECT id FROM evidence WHERE match_id=?", (int(match_id),)).fetchone())
                if not evidence:
                    raise ValidationError("Evidence does not exist.")
                db.execute("UPDATE evidence SET image_path=? WHERE id=?", (reference, evidence["id"]))
                db.execute("UPDATE potential_matches SET evidence_path=? WHERE id=?", (reference, int(match_id)))
            self._audit_system("EVIDENCE_ENCRYPTED", "potential_match", str(match_id), {"reference": reference})
    
        def submit_cctv(self, actor: str, case_id: str, station_location: str, filename: str, content: bytes, capture_datetime: str = "", description: str = "") -> dict[str, Any]:
            user = self._require(actor, "submit_cctv")
            case = self.get_case(actor, case_id)
            if not case:
                raise ValidationError("Case does not exist or is not available to this user.")
            if not self.case_allows_ai_processing(case_id):
                raise AuthorizationError("CCTV processing is blocked until police verification activates this case.")
            safe_name = self._safe_media_name(filename, VIDEO_EXTENSIONS)
            if not content or len(content) > MAX_CCTV_UPLOAD_BYTES:
                raise ValidationError("CCTV upload is empty or exceeds the configured file-size limit.")
            if not self._looks_like_video(safe_name, content):
                raise ValidationError("CCTV upload content does not match its declared video format.")
            CCTV_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            stored_name = f"{uuid4().hex}_{safe_name}"
            destination = CCTV_UPLOADS_DIR / stored_name
            destination.write_bytes(content)
            with self._connection() as db:
                cursor = db.execute("INSERT INTO cctv_submissions(case_id, station_location, uploading_user, stored_name, capture_datetime, description, processing_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING_PROCESSING', ?)",
                    (case_id, station_location.strip(), actor, stored_name, capture_datetime.strip(), description.strip(), _now()))
                submission = _row(db.execute("SELECT * FROM cctv_submissions WHERE id = ?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "CCTV_SUBMITTED", "cctv_submission", str(submission["id"]), {"case_id": case_id, "status": "PENDING_PROCESSING"})
            return submission  # type: ignore[return-value]
    
        def assign_station(self, actor: str, case_id: str, station_code: str, status: str = "ACTIVE") -> dict[str, Any]:
            user = self._require(actor, "manage_cases")
            if status not in ASSIGNMENT_STATUSES:
                raise ValidationError("Station assignment status must be ACTIVE, PENDING, or CLOSED.")
            if not self._case_for(case_id):
                raise ValidationError("Case does not exist.")
            with self._connection() as db:
                db.execute("INSERT INTO case_station_assignments(case_id, station_code, assignment_status, assigned_at, assigned_by) VALUES (?, ?, ?, ?, ?) ON CONFLICT(case_id, station_code) DO UPDATE SET assignment_status=excluded.assignment_status, assigned_at=excluded.assigned_at, assigned_by=excluded.assigned_by", (case_id, self._identifier(station_code, "station code"), status, _now(), actor))
                assignment = _row(db.execute("SELECT * FROM case_station_assignments WHERE case_id=? AND station_code=?", (case_id, station_code)).fetchone())
            self._audit(user, "CASE_STATION_ASSIGNED", "case", case_id, {"station_code": station_code, "status": status})
            return assignment  # type: ignore[return-value]
    
        def list_station_assignments(self, actor: str, case_id: str) -> list[dict[str, Any]]:
            """Return station assignments only to staff authorized for the case."""
            user = self._require(actor, "manage_cases", allow_any={"view_internal", "review_matches"})
            case = self._case_for(case_id)
            if not case:
                raise ValidationError("Case does not exist.")
            self._assert_case_access(user, case)
            with self._connection() as db:
                return [_row(row) for row in db.execute("SELECT * FROM case_station_assignments WHERE case_id=? ORDER BY station_code", (case_id,))]
    
        def get_authorized_case_stations(self, case_id: str) -> list[str]:
            """Return only the owning station and explicitly active case assignments."""
            case = self._case_for(case_id)
            if not case:
                raise ValidationError("Case does not exist.")
            with self._connection() as db:
                assigned = [row[0] for row in db.execute("SELECT station_code FROM case_station_assignments WHERE case_id=? AND assignment_status='ACTIVE'", (case_id,))]
            return sorted({case["authorized_station"], *assigned})
    
        def notification_match_context(self, match_id: int) -> dict[str, Any]:
            """Trusted internal context for templates; never returned directly to a parent."""
            try:
                match_id = int(match_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Notification match ID is invalid.") from exc
            with self._connection() as db:
                context = _row(db.execute("""SELECT m.*, c.parent_username, c.authorized_station,
                    (SELECT e.id FROM evidence e WHERE e.match_id=m.id ORDER BY e.id LIMIT 1) AS evidence_id
                    FROM potential_matches m JOIN cases c ON c.case_id=m.case_id WHERE m.id=?""", (match_id,)).fetchone())
                observation = _row(db.execute("""SELECT o.observed_at, c.camera_id, c.camera_name, c.station_code
                    FROM match_observations o JOIN cameras c ON c.camera_id=o.camera_id
                    WHERE o.match_id=? ORDER BY o.observed_at DESC LIMIT 1""", (match_id,)).fetchone())
            if not context:
                raise ValidationError("Potential match does not exist.")
            context["last_observed"] = observation
            return context
    
        def list_notifications(self, actor: str) -> list[dict[str, Any]]:
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
            with self._connection() as db:
                if user["role"] == "ADMIN":
                    rows = db.execute("SELECT * FROM notifications ORDER BY created_at DESC").fetchall()
                else:
                    rows = db.execute("SELECT * FROM notifications WHERE recipient_user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
            return [_row(row) for row in rows]
    
        def list_notifications_for_user(self, user_id: int) -> list[dict[str, Any]]:
            return self.list_notifications(self._active_user_by_id(user_id)["username"])
    
        def mark_notification_read(self, actor: str, notification_id: int) -> dict[str, Any]:
            user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
            try:
                notification_id = int(notification_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Notification ID is invalid.") from exc
            with self._connection() as db:
                notification = _row(db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone())
                if not notification:
                    raise ValidationError("Notification does not exist.")
                if user["role"] != "ADMIN" and notification["recipient_user_id"] != user["id"]:
                    raise AuthorizationError("This notification is not available to the selected user.")
                if notification["status"] not in {"READ", "FAILED", "CANCELLED"}:
                    db.execute("UPDATE notifications SET status='READ', read_at=? WHERE id=?", (_now(), notification_id))
                updated = _row(db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone())
            self._audit(user, "NOTIFICATION_READ", "notification", str(notification_id), {"case_id": notification["case_id"]})
            return updated  # type: ignore[return-value]
    
        def record_match_observation(self, actor: str, match_id: int, camera_id: str, observed_at: str | None = None) -> dict[str, Any]:
            """Record an existing registered camera observation; this is not GPS tracking."""
            user = self._require(actor, "manage_cases", allow_any={"review_matches"})
            context = self.notification_match_context(match_id)
            self._assert_case_access(user, self._case_for(context["case_id"]) or {})
            camera_id = self._identifier(camera_id, "camera ID")
            with self._connection() as db:
                camera = _row(db.execute("SELECT * FROM cameras WHERE camera_id=? AND active=1", (camera_id,)).fetchone())
                if not camera or camera["station_code"] not in self.get_authorized_case_stations(context["case_id"]):
                    raise AuthorizationError("Camera is not an authorized active camera for this case.")
                timestamp = observed_at or _now()
                try:
                    cursor = db.execute("INSERT INTO match_observations(match_id, camera_id, observed_at, created_at) VALUES (?, ?, ?, ?)", (int(match_id), camera_id, timestamp, _now()))
                except sqlite3.IntegrityError as exc:
                    raise ValidationError("This camera observation already exists.") from exc
                observation = _row(db.execute("SELECT * FROM match_observations WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._audit(user, "MATCH_OBSERVATION_RECORDED", "potential_match", str(match_id), {"case_id": context["case_id"], "camera_id": camera_id})
            return observation  # type: ignore[return-value]
    
        def register_camera(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
            self._require(actor, "manage_cases")
            camera_id = self._identifier(str(data.get("camera_id", "")), "camera ID")
            latitude, longitude = data.get("latitude"), data.get("longitude")
            if latitude is not None and (not self._coordinate(latitude, -90, 90) or not self._coordinate(longitude, -180, 180)):
                raise ValidationError("Camera latitude/longitude must be valid coordinates when provided.")
            with self._connection() as db:
                db.execute("INSERT INTO cameras(camera_id, station_code, camera_name, latitude, longitude, location_description, active) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(camera_id) DO UPDATE SET station_code=excluded.station_code, camera_name=excluded.camera_name, latitude=excluded.latitude, longitude=excluded.longitude, location_description=excluded.location_description, active=excluded.active", (camera_id, self._identifier(str(data.get("station_code", "")), "station code"), str(data.get("camera_name", "")).strip() or "Unnamed camera", latitude, longitude, str(data.get("location_description", "")).strip(), int(bool(data.get("active", True)))))
                camera = _row(db.execute("SELECT * FROM cameras WHERE camera_id=?", (camera_id,)).fetchone())
            return camera  # type: ignore[return-value]
    
        def metrics(self, actor: str) -> dict[str, int]:
            cases = self.list_cases(actor)
            matches = self.list_matches(actor)
            return {"active_cases": sum(case["case_status"] == "ACTIVE" for case in cases), "potential_matches": len(matches), "pending_reviews": sum(match["status"] == "PENDING" for match in matches), "verified_matches": sum(match["status"] == "VERIFIED" for match in matches), "rejected_matches": sum(match["status"] == "REJECTED" for match in matches), "cctv_runs": self._count_runs(cases)}
    
        def list_audit_logs(self, actor: str) -> list[dict[str, Any]]:
            self._require(actor, "view_audit")
            with self._connection() as db:
                return [_row(row) for row in db.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC, id DESC")]
    
        def _audit(self, user: dict[str, Any], action: str, resource_type: str, resource_id: str, details: dict[str, Any], outcome: str = "SUCCESS") -> None:
            with self._connection() as db:
                db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user["id"], user["role"], action, resource_type, resource_id, _now(), self._json_text(details), outcome))
    
        def _audit_system(self, action: str, resource_type: str, resource_id: str, details: dict[str, Any]) -> None:
            """Log a non-human pipeline event without inventing a user identity."""
            with self._connection() as db:
                db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (None, "SYSTEM", action, resource_type, resource_id, _now(), self._json_text(details), "SUCCESS"))
    
        def _dispatch_notification_event(self, match_id: int, event: str) -> None:
            """Keep a notification-provider failure visible without changing review state."""
            try:
                from .notification_service import NotificationService
                NotificationService(self).notify_match_event(match_id, event)
            except Exception as exc:
                self._audit_system("NOTIFICATION_FAILED", "potential_match", str(match_id), {"event": event, "reason": str(exc)[:300]})
    
        def _require(self, actor: str, permission: str, allow_any: set[str] | None = None) -> dict[str, Any]:
            user = self.get_user(actor)
            if not user or not user.get("is_active", 1):
                raise AuthorizationError("Select a valid local prototype user.")
            permissions = ROLE_PERMISSIONS[user["role"]]
            if permission not in permissions and not (allow_any and permissions.intersection(allow_any)):
                raise AuthorizationError("This role is not permitted to perform that action.")
            return user
    
        def _active_user_by_id(self, user_id: int) -> dict[str, Any]:
            user = self.get_user_by_id(user_id)
            if not user or not user.get("is_active", 1):
                raise AuthorizationError("Your session is no longer authorized. Please sign in again.")
            return user
    
        def _validate_case(self, data: dict[str, Any]) -> dict[str, Any]:
            case_id = self._identifier(str(data.get("case_id", "")), "case ID")
            child_id = self._identifier(str(data.get("child_id", "")), "child ID")
            child_name = str(data.get("child_name", "")).strip()
            description = str(data.get("description", "")).strip()
            if not child_name or not description:
                raise ValidationError("Case requires child name and description.")
            age = data.get("age")
            if age not in (None, "") and (not isinstance(age, int) or isinstance(age, bool) or age < 0):
                raise ValidationError("Age must be a non-negative whole number when provided.")
            reference_image = self._safe_media_name(str(data.get("reference_image", "")), IMAGE_EXTENSIONS)
            status = data.get("case_status", "ACTIVE")
            if status not in CASE_STATUSES:
                raise ValidationError("Case status must be DRAFT, ACTIVE, PAUSED, UNDER_REVIEW, RESOLVED, CLOSED, or ARCHIVED.")
            station = self._identifier(str(data.get("authorized_station", "")), "authorized station")
            return {"case_id": case_id, "child_id": child_id, "child_name": child_name, "age": age or None, "description": description, "reference_image": reference_image, "case_status": status, "authorized_station": station, "region": str(data.get("region", "")).strip() or None, "station_code": str(data.get("station_code", station)).strip(), "parent_username": str(data.get("parent_username", "")).strip() or None}
    
        @staticmethod
        def _identifier(value: str, label: str) -> str:
            try:
                safe_filename(value)
            except ValueError as exc:
                raise ValidationError(f"{label.capitalize()} must be a simple identifier, not a path.") from exc
            return value
    
        @staticmethod
        def _safe_media_name(value: str, allowed_extensions: set[str]) -> str:
            try:
                name = safe_filename(value)
            except ValueError as exc:
                raise ValidationError("File name must not contain a path.") from exc
            if any(marker in name.lower() for marker in ("%2e", "%2f", "%5c")):
                raise ValidationError("File name must not contain encoded path traversal.")
            if Path(name).suffix.lower() not in allowed_extensions:
                raise ValidationError(f"Unsupported file type. Allowed: {', '.join(sorted(allowed_extensions))}.")
            return name
    
        @staticmethod
        def _safe_evidence_path(value: Any) -> str | None:
            if not value:
                return None
            candidate = Path(str(value))
            if candidate.suffix.lower() not in IMAGE_EXTENSIONS | {".json", ".fernet"}:
                raise ValidationError("Evidence reference is invalid.")
            return candidate.name
    
        @staticmethod
        def _json_text(value: Any) -> str:
            def redact(item: Any) -> Any:
                if isinstance(item, dict):
                    return {str(key): "[REDACTED]" if any(word in str(key).lower() for word in ("password", "secret", "token", "api_key", "hash")) else redact(value) for key, value in item.items()}
                if isinstance(item, list):
                    return [redact(value) for value in item]
                return item
            cleaned = redact(value)
            return json.dumps(cleaned, sort_keys=True) if isinstance(cleaned, (dict, list)) else str(cleaned)
    
        @staticmethod
        def _email(value: str) -> str:
            normalized = value.strip().lower()
            if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
                raise ValidationError("Email must be a valid address.")
            return normalized
    
        @staticmethod
        def _looks_like_video(filename: str, content: bytes) -> bool:
            extension = Path(filename).suffix.lower()
            if extension == ".avi":
                return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"AVI "
            if extension == ".mp4":
                return len(content) >= 12 and content[4:8] == b"ftyp"
            if extension == ".mov":
                return len(content) >= 12 and content[4:8] == b"ftyp"
            return False
    
        def validate_reference_upload(self, filename: str, content: bytes) -> str:
            """Validate image type, bounded bytes, and a lightweight image signature."""
            safe_name = self._safe_media_name(filename, IMAGE_EXTENSIONS)
            if not content or len(content) > MAX_REFERENCE_IMAGE_BYTES:
                raise ValidationError("Reference image is empty or exceeds the configured file-size limit.")
            suffix = Path(safe_name).suffix.lower()
            jpeg = len(content) >= 3 and content[:3] == b"\xff\xd8\xff"
            png = len(content) >= 8 and content[:8] == b"\x89PNG\r\n\x1a\n"
            if (suffix in {".jpg", ".jpeg"} and not jpeg) or (suffix == ".png" and not png):
                raise ValidationError("Reference image content does not match its declared format.")
            return safe_name
    
        @staticmethod
        def _locked(user: dict[str, Any]) -> bool:
            value = user.get("lockout_until")
            if not value:
                return False
            try:
                return datetime.fromisoformat(value) > datetime.now(timezone.utc)
            except ValueError:
                return True
    
        def _audit_login_failure(self, db: sqlite3.Connection, user: dict[str, Any] | None, identity: str) -> None:
            if user:
                failures = int(user.get("failed_login_count") or 0) + 1
                lockout = None
                if failures >= LOGIN_MAX_FAILURES:
                    from datetime import timedelta
                    lockout = (datetime.now(timezone.utc) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).isoformat()
                db.execute("UPDATE users SET failed_login_count=?, lockout_until=? WHERE id=?", (failures, lockout, user["id"]))
                db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user["id"], user["role"], "LOGIN_FAILURE", "authentication", str(user["id"]), _now(), self._json_text({"identity": identity}), "FAILURE"))
            else:
                db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (None, None, "LOGIN_FAILURE", "authentication", "unknown", _now(), self._json_text({"identity": identity}), "FAILURE"))
    
        @staticmethod
        def _coordinate(value: Any, lower: float, upper: float) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and lower <= value <= upper
    
        def _case_for(self, case_id: str) -> dict[str, Any] | None:
            with self._connection() as db:
                return _row(db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone())
    
        def _case_allowed(self, user: dict[str, Any], case: dict[str, Any]) -> bool:
            if user["role"] == "ADMIN":
                return True
            if user["role"] == "PARENT":
                return case.get("parent_username") == user["username"]
            return not user.get("station") or user["station"] in self.get_authorized_case_stations(case["case_id"])
    
        def _assert_case_access(self, user: dict[str, Any], case: dict[str, Any]) -> None:
            if not self._case_allowed(user, case):
                raise AuthorizationError("This case is not available to the selected user.")
    
        @staticmethod
        def _parent_safe_case(case: dict[str, Any]) -> dict[str, Any]:
            state = case.get("lifecycle_state") or case.get("case_status")
            safe_status = "Case active" if state == "ACTIVE" else "Awaiting police verification" if state == "PENDING_POLICE_VERIFICATION" else "Report submitted"
            result = {key: case.get(key) for key in ("case_id", "child_id", "child_name", "case_status", "created_at", "updated_at")}
            result.update({"lifecycle_state": state, "police_verification_status": safe_status})
            return result
    
        @staticmethod
        def _parent_safe_match(match: dict[str, Any]) -> dict[str, Any]:
            return {key: match[key] for key in ("id", "case_id", "child_id", "status", "created_at", "reviewed_at")}
    
        def _count_runs(self, cases: list[dict[str, Any]]) -> int:
            case_ids = [case["case_id"] for case in cases]
            if not case_ids:
                return 0
            placeholders = ",".join("?" for _ in case_ids)
            with self._connection() as db:
                return int(db.execute(f"SELECT COUNT(DISTINCT run_id) FROM potential_matches WHERE case_id IN ({placeholders})", case_ids).fetchone()[0])
    def create_user(self, username: str, role: str, station: str | None = None, password: str | None = None, email: str | None = None, actor: str | None = None) -> dict[str, Any]:
        """Create a user; callers should pass an ADMIN actor outside bootstrap/tests."""
        self.initialize()
        administrator = self._require(actor, "manage_users") if actor else None
        username = self._identifier(username, "username")
        if role not in ROLES:
            raise ValidationError("Role must be ADMIN, POLICE, REVIEWER, or PARENT.")
        normalized_email = self._email(email) if email else None
        password_hash = hash_password(password) if password is not None else None
        with self._connection() as db:
            try:
                db.execute("INSERT INTO users(username, role, station, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)", (username, role, station, normalized_email, password_hash, _now()))
            except sqlite3.IntegrityError as exc:
                raise ValidationError("Username or email already exists.") from exc
        created = self.get_user(username)
        if administrator and created:
            self._audit(administrator, "USER_CREATED", "user", str(created["id"]), {"role": role, "station": station})
        return created  # type: ignore[return-value]

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._connection() as db:
            return _row(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connection() as db:
            return _row(db.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())

    def user_count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def credentialed_active_user_count(self) -> int:
        """Count accounts that can actually use the Sprint 5 login flow."""
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND password_hash IS NOT NULL").fetchone()[0])

    def bootstrap_admin(self, username: str, email: str, password: str) -> dict[str, Any]:
        """Create the first admin only when the database has no users."""
        if self.credentialed_active_user_count():
            existing = self.get_user(username)
            if not existing:
                raise AuthorizationError("An administrator already exists; use an authenticated admin to create users.")
            return existing
        existing = self.get_user(username)
        if existing:
            with self._connection() as db:
                db.execute("UPDATE users SET role='ADMIN', email=?, password_hash=?, is_active=1, failed_login_count=0, lockout_until=NULL WHERE id=?", (self._email(email), hash_password(password), existing["id"]))
            return self.get_user(username)  # type: ignore[return-value]
        return self.create_user(username, "ADMIN", station="HQ", password=password, email=email)

    def authenticate(self, username_or_email: str, password: str) -> dict[str, Any] | None:
        """Return an active user only after rate-limit and Argon2 verification."""
        self.initialize()
        identity = str(username_or_email).strip().lower()
        with self._connection() as db:
            user = _row(db.execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?", (identity, identity)).fetchone())
            if not user or not user.get("is_active") or self._locked(user):
                self._audit_login_failure(db, user, identity)
                return None
            if not verify_password(user.get("password_hash"), password):
                self._audit_login_failure(db, user, identity)
                return None
            replacement_hash = hash_password(password) if password_needs_rehash(user.get("password_hash")) else user.get("password_hash")
            db.execute("UPDATE users SET failed_login_count=0, lockout_until=NULL, last_login_at=?, password_hash=? WHERE id=?", (iso_now(), replacement_hash, user["id"]))
            authenticated = _row(db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        self._audit(authenticated, "LOGIN_SUCCESS", "user", str(authenticated["id"]), {"outcome": "success"})
        return authenticated

    def record_logout(self, user_id: int) -> None:
        user = self._active_user_by_id(user_id)
        self._audit(user, "LOGOUT", "user", str(user["id"]), {"outcome": "success"})

    def deactivate_user(self, actor: str, username: str, active: bool) -> dict[str, Any]:
        administrator = self._require(actor, "manage_users")
        target = self.get_user(username)
        if not target:
            raise ValidationError("User does not exist.")
        with self._connection() as db:
            db.execute("UPDATE users SET is_active=? WHERE id=?", (int(active), target["id"]))
        result = self.get_user(username)
        self._audit(administrator, "USER_ACTIVATED" if active else "USER_DEACTIVATED", "user", str(target["id"]), {})
        return result  # type: ignore[return-value]

    def change_user_role(self, actor: str, username: str, role: str) -> dict[str, Any]:
        administrator = self._require(actor, "manage_users")
        if role not in ROLES:
            raise ValidationError("Role must be ADMIN, POLICE, REVIEWER, or PARENT.")
        target = self.get_user(username)
        if not target:
            raise ValidationError("User does not exist.")
        with self._connection() as db:
            db.execute("UPDATE users SET role=? WHERE id=?", (role, target["id"]))
        result = self.get_user(username)
        self._audit(administrator, "USER_ROLE_CHANGED", "user", str(target["id"]), {"role": role})
        return result  # type: ignore[return-value]

    def change_password(self, actor: str, current_password: str, new_password: str) -> None:
        """Authenticated password change; Argon2 and minimum-length policy remain central."""
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
        if not verify_password(user.get("password_hash"), current_password):
            self._audit(user, "PASSWORD_CHANGE_FAILURE", "user", str(user["id"]), {}, "FAILURE")
            raise AuthorizationError("Current credentials could not be verified.")
        replacement = hash_password(new_password)
        with self._connection() as db:
            db.execute("UPDATE users SET password_hash=?, failed_login_count=0, lockout_until=NULL WHERE id=?", (replacement, user["id"]))
        self._audit(user, "PASSWORD_CHANGED", "user", str(user["id"]), {})

    def admin_reset_password(self, actor: str, username: str, new_password: str, reason: str) -> None:
        administrator = self._require(actor, "manage_users")
        target = self.get_user(username)
        if not target or not reason.strip():
            raise ValidationError("A target user and reset reason are required.")
        with self._connection() as db:
            db.execute("UPDATE users SET password_hash=?, failed_login_count=0, lockout_until=NULL WHERE id=?", (hash_password(new_password), target["id"]))
        self._audit(administrator, "PASSWORD_RESET_ADMIN_ASSISTED", "user", str(target["id"]), {"reason": reason.strip()[:300]})

    def record_login(self, actor: str) -> None:
        """Audit a local demo identity selection; this is not authentication."""
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
        self._audit(user, "LOGIN", "user", str(user["id"]), {"prototype": True})

    def create_case(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
        user = self._require(actor, "manage_cases")
        case = self._validate_case(data)
        timestamp = _now()
        with self._connection() as db:
            try:
                db.execute("""INSERT INTO cases(case_id, child_id, child_name, age, description, reference_image,
                    case_status, created_by, authorized_station, region, station_code, parent_username, created_at, updated_at)
                    VALUES (:case_id, :child_id, :child_name, :age, :description, :reference_image, :case_status,
                    :created_by, :authorized_station, :region, :station_code, :parent_username, :created_at, :updated_at)""",
                    {**case, "created_by": actor, "created_at": timestamp, "updated_at": timestamp})
            except sqlite3.IntegrityError as exc:
                raise ValidationError("Case ID or child ID already exists.") from exc
        created = self.get_case(actor, case["case_id"])
        self._audit(user, "CASE_CREATED", "case", case["case_id"], {"station": case["authorized_station"]})
        return created  # type: ignore[return-value]

    def create_preliminary_report(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
        """Let a parent submit a report without activating an investigation."""
        parent = self._require(actor, "view_own_case")
        if parent["role"] != "PARENT":
            raise AuthorizationError("Preliminary reports are submitted by the reporting parent or guardian.")
        case = self._validate_case({**data, "case_status": "DRAFT", "parent_username": actor})
        timestamp = _now()
        with self._connection() as db:
            try:
                db.execute("""INSERT INTO cases(case_id, child_id, child_name, age, description, reference_image, case_status,
                    lifecycle_state, created_by, authorized_station, region, station_code, parent_username, last_seen_date,
                    last_seen_time, last_seen_location, police_complaint_status, police_complaint_number,
                    police_complaint_date, complaint_police_station, created_at, updated_at)
                    VALUES (:case_id, :child_id, :child_name, :age, :description, :reference_image, 'DRAFT',
                    'PENDING_POLICE_VERIFICATION', :created_by, :authorized_station, :region, :station_code, :parent_username,
                    :last_seen_date, :last_seen_time, :last_seen_location, 'AWAITING_VERIFICATION', :police_complaint_number,
                    :police_complaint_date, :complaint_police_station, :created_at, :updated_at)""",
                    {**case, "created_by": actor, "last_seen_date": str(data.get("last_seen_date", "")).strip() or None,
                     "last_seen_time": str(data.get("last_seen_time", "")).strip() or None,
                     "last_seen_location": str(data.get("last_seen_location", "")).strip() or None,
                     "police_complaint_number": self._identifier(str(data.get("police_complaint_number", "UNVERIFIED")), "complaint reference"),
                     "police_complaint_date": str(data.get("police_complaint_date", "")).strip() or None,
                     "complaint_police_station": str(data.get("complaint_police_station", case["authorized_station"])).strip()[:120],
                     "created_at": timestamp, "updated_at": timestamp})
            except sqlite3.IntegrityError as exc:
                raise ValidationError("Case ID or child ID already exists.") from exc
        created = self.get_case(actor, case["case_id"])
        self._audit(parent, "PRELIMINARY_REPORT_CREATED", "case", case["case_id"], {"status": "PENDING_POLICE_VERIFICATION"})
        return created  # type: ignore[return-value]

    def verify_police_complaint(self, actor: str, case_id: str, complaint_number: str, complaint_date: str,
                                police_station: str, notes: str = "") -> dict[str, Any]:
        """Police/admin approval is the only path from an intake report to ACTIVE."""
        officer = self._require(actor, "manage_cases")
        case = self._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        self._assert_case_access(officer, case)
        if (case.get("lifecycle_state") or case["case_status"]) != "PENDING_POLICE_VERIFICATION":
            raise ValidationError("Only reports awaiting police verification can be activated.")
        complaint_number = self._identifier(complaint_number, "complaint reference")
        if not complaint_date.strip() or not police_station.strip():
            raise ValidationError("Complaint date and police station are required for verification.")
        with self._connection() as db:
            db.execute("""UPDATE cases SET case_status='ACTIVE', lifecycle_state='ACTIVE', state_changed_at=?, updated_at=?,
                police_complaint_status='VERIFIED', police_complaint_number=?, police_complaint_date=?,
                complaint_police_station=?, police_verified_by=?, police_verified_at=?, police_verification_notes=? WHERE case_id=?""",
                (_now(), _now(), complaint_number, complaint_date.strip()[:40], police_station.strip()[:120], actor, _now(), notes.strip()[:500], case_id))
        result = self.get_case(actor, case_id)
        self._audit(officer, "POLICE_COMPLAINT_VERIFIED", "case", case_id, {"from": "PENDING_POLICE_VERIFICATION", "to": "ACTIVE"})
        return result  # type: ignore[return-value]

    def case_allows_ai_processing(self, case_id: str) -> bool:
        """Explicit gate: legacy active cases work; unverified intake reports do not."""
        case = self._case_for(case_id)
        return bool(case and (case.get("lifecycle_state") or case.get("case_status")) == "ACTIVE")

    def _reference_access(self, actor: str, case_id: str, owner_only: bool = False) -> dict[str, Any]:
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches"})
        case = self._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        self._assert_case_access(user, case)
        if owner_only and case.get("parent_username") != actor:
            raise AuthorizationError("Only the reporting parent or guardian may manage this reference.")
        return user

    def add_child_reference(self, actor: str, case_id: str, filename: str, opaque_reference: str) -> dict[str, Any]:
        user = self._reference_access(actor, case_id, owner_only=self.get_user(actor).get("role") == "PARENT")  # type: ignore[union-attr]
        self._safe_media_name(filename, IMAGE_EXTENSIONS)
        reference = self._safe_evidence_path(opaque_reference) or ""
        if not reference.endswith(".fernet"):
            raise ValidationError("Child references require controlled encrypted storage.")
        with self._connection() as db:
            cursor = db.execute("INSERT INTO child_reference_images(case_id, uploaded_by, opaque_reference, created_at) VALUES (?, ?, ?, ?)", (case_id, actor, reference, _now()))
            row = _row(db.execute("SELECT * FROM child_reference_images WHERE id=?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "CHILD_REFERENCE_UPLOADED", "child_reference", str(row["id"]), {"case_id": case_id})
        return row  # type: ignore[return-value]

    def add_parent_reference(self, actor: str, case_id: str, relationship_label: str, filename: str, opaque_reference: str) -> dict[str, Any]:
        user = self._reference_access(actor, case_id, owner_only=True)
        self._safe_media_name(filename, IMAGE_EXTENSIONS)
        reference = self._safe_evidence_path(opaque_reference) or ""
        if not reference.endswith(".fernet") or not relationship_label.strip():
            raise ValidationError("A relationship label and controlled encrypted reference are required.")
        with self._connection() as db:
            cursor = db.execute("INSERT INTO parent_reference_images(case_id, owner_username, relationship_label, opaque_reference, created_at) VALUES (?, ?, ?, ?, ?)", (case_id, actor, relationship_label.strip()[:80], reference, _now()))
            row = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "PARENT_REFERENCE_UPLOADED", "parent_reference", str(row["id"]), {"case_id": case_id, "relationship": relationship_label.strip()[:80]})
        return row  # type: ignore[return-value]

    def list_parent_references(self, actor: str, case_id: str) -> list[dict[str, Any]]:
        user = self._reference_access(actor, case_id)
        with self._connection() as db:
            rows = [_row(row) for row in db.execute("SELECT id, case_id, relationship_label, status, created_at FROM parent_reference_images WHERE case_id=? AND status='ACTIVE'", (case_id,))]
        self._audit(user, "PARENT_REFERENCE_LIST_VIEWED", "case", case_id, {})
        return [row for row in rows if row]

    def list_age_progression_references(self, actor: str, case_id: str) -> list[dict[str, Any]]:
        user = self._reference_access(actor, case_id)
        with self._connection() as db:
            rows = [_row(row) for row in db.execute("SELECT id, case_id, target_age, provider, status, created_at, reviewed_at FROM age_progression_references WHERE case_id=? ORDER BY created_at DESC", (case_id,))]
        self._audit(user, "AGE_PROGRESSION_LIST_VIEWED", "case", case_id, {})
        return [row for row in rows if row]

    def list_pending_age_progression_references(self, actor: str) -> list[dict[str, Any]]:
        user = self._require(actor, "review_matches")
        with self._connection() as db:
            rows = [_row(row) for row in db.execute("SELECT id, case_id, target_age, provider, status, created_at FROM age_progression_references WHERE status='PENDING_REVIEW' ORDER BY created_at ASC")]
        return [row for row in rows if row and self._case_allowed(user, self._case_for(row["case_id"]) or {})]

    def delete_parent_reference(self, actor: str, reference_id: int, reason: str, explicitly_confirmed: bool = False) -> None:
        if not explicitly_confirmed or not reason.strip():
            raise ValidationError("Explicit confirmation and a reason are required to delete a parent reference.")
        with self._connection() as db:
            reference = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (int(reference_id),)).fetchone())
            if not reference:
                raise ValidationError("Parent reference does not exist.")
            user = self._reference_access(actor, reference["case_id"], owner_only=True)
            if reference.get("legal_hold"):
                raise AuthorizationError("A reference under legal hold cannot be deleted.")
            db.execute("UPDATE parent_reference_images SET status='DELETED', deleted_at=? WHERE id=?", (_now(), reference_id))
        self._audit(user, "PARENT_REFERENCE_DELETED", "parent_reference", str(reference_id), {"case_id": reference["case_id"], "logical": True})

    def set_parent_reference_legal_hold(self, actor: str, reference_id: int, enabled: bool, reason: str) -> None:
        admin = self._require(actor, "manage_users")
        if not reason.strip():
            raise ValidationError("A legal-hold reason is required.")
        with self._connection() as db:
            reference = _row(db.execute("SELECT * FROM parent_reference_images WHERE id=?", (int(reference_id),)).fetchone())
            if not reference:
                raise ValidationError("Parent reference does not exist.")
            db.execute("UPDATE parent_reference_images SET legal_hold=? WHERE id=?", (int(enabled), reference_id))
        self._audit(admin, "PARENT_REFERENCE_LEGAL_HOLD_SET" if enabled else "PARENT_REFERENCE_LEGAL_HOLD_RELEASED", "parent_reference", str(reference_id), {"case_id": reference["case_id"]})

    def create_age_progression_reference(self, actor: str, case_id: str, child_reference_id: int, target_age: int,
                                         provider: str, opaque_reference: str | None) -> dict[str, Any]:
        user = self._reference_access(actor, case_id)
        case = self._case_for(case_id) or {}
        if not isinstance(target_age, int) or isinstance(target_age, bool) or target_age < int(case.get("age") or 0) or target_age > 120:
            raise ValidationError("Target age must be a valid age at or above the child's recorded age.")
        with self._connection() as db:
            source = _row(db.execute("SELECT * FROM child_reference_images WHERE id=? AND case_id=? AND status='ACTIVE'", (int(child_reference_id), case_id)).fetchone())
            if not source:
                raise ValidationError("An active controlled child reference is required.")
            cursor = db.execute("INSERT INTO age_progression_references(case_id, source_child_reference_id, target_age, opaque_reference, provider, status, requested_by, created_at) VALUES (?, ?, ?, ?, ?, 'PENDING_REVIEW', ?, ?)", (case_id, child_reference_id, target_age, self._safe_evidence_path(opaque_reference) if opaque_reference else None, provider[:120], actor, _now()))
            row = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "AGE_PROGRESSION_GENERATED", "age_progression_reference", str(row["id"]), {"case_id": case_id, "target_age": target_age, "status": "PENDING_REVIEW", "provider": provider[:120]})
        return row  # type: ignore[return-value]

    def review_age_progression_reference(self, actor: str, reference_id: int, approve: bool) -> dict[str, Any]:
        reviewer = self._require(actor, "review_matches")
        with self._connection() as db:
            reference = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
            if not reference:
                raise ValidationError("Age-progression reference does not exist.")
            self._assert_case_access(reviewer, self._case_for(reference["case_id"]) or {})
            if reference["status"] != "PENDING_REVIEW":
                raise ValidationError("Only a PENDING_REVIEW age-progression reference may be reviewed.")
            status = "APPROVED" if approve else "REJECTED"
            db.execute("UPDATE age_progression_references SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?", (status, actor, _now(), reference_id))
            result = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (reference_id,)).fetchone())
        self._audit(reviewer, "AGE_PROGRESSION_APPROVED" if approve else "AGE_PROGRESSION_REJECTED", "age_progression_reference", str(reference_id), {"case_id": reference["case_id"]})
        return result  # type: ignore[return-value]

    def attach_age_progression_output(self, reference_id: int, opaque_reference: str) -> None:
        """System boundary for a provider result; no user-supplied paths are accepted."""
        reference = self._safe_evidence_path(opaque_reference) or ""
        if not reference.endswith(".fernet"):
            raise ValidationError("Generated reference requires controlled encrypted storage.")
        with self._connection() as db:
            if not db.execute("SELECT id FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone():
                raise ValidationError("Age-progression reference does not exist.")
            db.execute("UPDATE age_progression_references SET opaque_reference=? WHERE id=?", (reference, reference_id))

    def _row_for_progression(self, reference_id: int) -> dict[str, Any]:
        with self._connection() as db:
            row = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
        if not row:
            raise ValidationError("Age-progression reference does not exist.")
        return row

    def add_age_progression_embedding(self, actor: str, reference_id: int, embedding: list[float]) -> dict[str, Any]:
        user = self._require(actor, "review_matches")
        if not isinstance(embedding, list) or not embedding or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in embedding):
            raise ValidationError("Embedding must contain finite numeric values.")
        with self._connection() as db:
            reference = _row(db.execute("SELECT * FROM age_progression_references WHERE id=?", (int(reference_id),)).fetchone())
            if not reference or reference["status"] != "APPROVED":
                raise ValidationError("Only an approved age-progression reference may become a matching reference.")
            self._assert_case_access(user, self._case_for(reference["case_id"]) or {})
            cursor = db.execute("INSERT INTO child_reference_embeddings(case_id, progression_reference_id, embedding_json, embedding_source, created_by, created_at) VALUES (?, ?, ?, 'AGE_PROGRESSED_REFERENCE', ?, ?)", (reference["case_id"], reference_id, json.dumps(embedding), actor, _now()))
            row = _row(db.execute("SELECT * FROM child_reference_embeddings WHERE id=?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "AGE_PROGRESSION_EMBEDDING_CREATED", "child_reference_embedding", str(row["id"]), {"case_id": reference["case_id"], "source": "AGE_PROGRESSED_REFERENCE"})
        return row  # type: ignore[return-value]

    def get_case(self, actor: str, case_id: str) -> dict[str, Any] | None:
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases"})
        with self._connection() as db:
            case = _row(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone())
        if not case:
            return None
        self._assert_case_access(user, case)
        return self._parent_safe_case(case) if user["role"] == "PARENT" else case

    def get_case_for_user(self, user_id: int, case_id: str) -> dict[str, Any] | None:
        """Authenticated-ID variant used by the dashboard session boundary."""
        user = self._active_user_by_id(user_id)
        return self.get_case(user["username"], case_id)

    def update_case(self, actor: str, case_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Allow only police/admin case-state updates and preserve safe fields."""
        user = self._require(actor, "manage_cases")
        existing = self._case_for(case_id)
        if not existing:
            raise ValidationError("Case does not exist.")
        self._assert_case_access(user, existing)
        allowed = {"child_name", "age", "description", "reference_image", "case_status", "authorized_station", "region", "station_code", "parent_username"}
        merged = {**existing, **{key: value for key, value in updates.items() if key in allowed}}
        validated = self._validate_case(merged)
        with self._connection() as db:
            db.execute("""UPDATE cases SET child_name=:child_name, age=:age, description=:description,
                reference_image=:reference_image, case_status=:case_status, authorized_station=:authorized_station,
                region=:region, station_code=:station_code, parent_username=:parent_username, updated_at=:updated_at
                WHERE case_id=:case_id""", {**validated, "updated_at": _now()})
        result = self.get_case(actor, case_id)
        self._audit(user, "CASE_UPDATED", "case", case_id, {"fields": sorted(set(updates).intersection(allowed))})
        return result  # type: ignore[return-value]

    def transition_case_state(self, actor: str, case_id: str, target: str, reason: str = "") -> dict[str, Any]:
        """Perform an explicitly allowed, audited case lifecycle transition."""
        user = self._require(actor, "manage_cases")
        case = self._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        self._assert_case_access(user, case)
        source = case.get("lifecycle_state") or case["case_status"]
        if target not in CASE_STATE_TRANSITIONS.get(source, set()):
            raise ValidationError(f"Case cannot transition from {source} to {target}.")
        with self._connection() as db:
            # Keep legacy case_status compatible with prior SQLite CHECK constraints;
            # lifecycle_state carries the richer Sprint 7 state machine.
            legacy_status = "CLOSED" if target in {"CLOSED", "ARCHIVED"} else "DRAFT" if target in {"DRAFT", "PENDING_POLICE_VERIFICATION"} else "ACTIVE"
            db.execute("UPDATE cases SET case_status=?, lifecycle_state=?, updated_at=?, state_changed_at=? WHERE case_id=?", (legacy_status, target, _now(), _now(), case_id))
        result = self.get_case(actor, case_id)
        self._audit(user, "CASE_CLOSED" if target == "CLOSED" else "CASE_STATE_CHANGED", "case", case_id, {"from": source, "to": target, "reason": reason.strip()[:300]})
        return result  # type: ignore[return-value]

    def list_cases(self, actor: str) -> list[dict[str, Any]]:
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases"})
        with self._connection() as db:
            rows = [_row(row) for row in db.execute("SELECT * FROM cases ORDER BY updated_at DESC")]
        allowed = [case for case in rows if case and self._case_allowed(user, case)]
        return [self._parent_safe_case(case) if user["role"] == "PARENT" else case for case in allowed]

    def list_cases_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return self.list_cases(self._active_user_by_id(user_id)["username"])

    def record_potential_match(self, data: dict[str, Any]) -> dict[str, Any]:
        """Store an AI result as PENDING; only review_match can change it."""
        self.initialize()
        required = {"case_id", "child_id", "track_id", "run_id", "frame_number", "video_name"}
        if missing := required - data.keys():
            raise ValidationError(f"Potential match is missing: {', '.join(sorted(missing))}")
        if data.get("status", "PENDING") != "PENDING":
            raise ValidationError("New AI potential matches must start as PENDING.")
        self._safe_media_name(str(data["video_name"]), VIDEO_EXTENSIONS)
        with self._connection() as db:
            case = db.execute("SELECT case_id, child_id, case_status, lifecycle_state FROM cases WHERE case_id = ?", (data["case_id"],)).fetchone()
            if not case or case["child_id"] != data["child_id"]:
                raise ValidationError("Potential match must reference its existing case and child ID.")
            if (case["lifecycle_state"] or case["case_status"]) != "ACTIVE":
                self._audit_system("POTENTIAL_MATCH_BLOCKED_CASE_NOT_ACTIVE", "case", data["case_id"], {"status": case["lifecycle_state"] or case["case_status"]})
                raise AuthorizationError("AI potential matches are blocked until the case is ACTIVE.")
            try:
                cursor = db.execute("""INSERT INTO potential_matches(case_id, child_id, track_id, run_id, frame_number, video_name,
                    face_score, clothing_score, accessory_score, physical_score, overall_score, status, evidence_path, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)""",
                    (data["case_id"], data["child_id"], int(data["track_id"]), str(data["run_id"]), int(data["frame_number"]),
                     data["video_name"], data.get("face_score"), data.get("clothing_score"), data.get("accessory_score"),
                     data.get("physical_score", data.get("physical_feature_score")), data.get("overall_score"),
                     self._safe_evidence_path(data.get("evidence_path")), self._json_text(data.get("reason", data.get("evidence_reasons", {}))), _now()))
            except sqlite3.IntegrityError as exc:
                raise ValidationError("A potential match for this case, run, and track already exists.") from exc
            match_id = cursor.lastrowid
            if data.get("evidence_path") or data.get("metadata_path"):
                db.execute("INSERT INTO evidence(match_id, image_path, metadata_path, frame_number, track_id, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (match_id, self._safe_evidence_path(data.get("evidence_path")), self._safe_evidence_path(data.get("metadata_path")), int(data["frame_number"]), int(data["track_id"]), str(data["run_id"]), _now()))
            row = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
        self._audit_system("POTENTIAL_MATCH_CREATED", "potential_match", str(match_id), {"case_id": data["case_id"], "run_id": str(data["run_id"]), "status": "PENDING"})
        self._dispatch_notification_event(match_id, "PENDING")
        return row  # type: ignore[return-value]

    def record_pipeline_match_for_child(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Bridge a pipeline event into the review store only when a managed case exists.

        A matcher event without a case record remains an existing local evidence event;
        it is never converted into a public notification.
        """
        child_id = self._identifier(str(data.get("child_id", "")), "child ID")
        with self._connection() as db:
            case = _row(db.execute("SELECT case_id FROM cases WHERE child_id=?", (child_id,)).fetchone())
        if not case:
            return None
        if not self.case_allows_ai_processing(case["case_id"]):
            self._audit_system("PIPELINE_MATCH_BLOCKED_CASE_NOT_ACTIVE", "case", case["case_id"], {"child_id": child_id})
            return None
        return self.record_potential_match({
            "case_id": case["case_id"], "child_id": child_id, "track_id": data["track_id"], "run_id": data["run_id"],
            "frame_number": data["frame_number"], "video_name": data["cctv_source"], "face_score": data.get("face_score"),
            "clothing_score": data.get("clothing_score"), "accessory_score": data.get("accessory_score"),
            "physical_feature_score": data.get("physical_feature_score"), "overall_score": data.get("overall_score"),
            "reason": data.get("evidence_reasons", {}), "evidence_path": Path(str(data.get("evidence_image", ""))).name,
            "metadata_path": Path(str(data.get("evidence_metadata", ""))).name,
        })

    def review_match(self, actor: str, match_id: int, action: str, notes: str = "", confirmed: bool = False) -> dict[str, Any]:
        user = self._require(actor, "review_matches")
        action_map = {"KEEP_PENDING": "PENDING", "VERIFY": "VERIFIED", "REJECT": "REJECTED"}
        if action not in action_map:
            raise ValidationError("Review action must be KEEP_PENDING, VERIFY, or REJECT.")
        if action == "VERIFY" and not confirmed:
            raise ValidationError("VERIFY requires explicit confirmation.")
        with self._connection() as db:
            match = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
            if not match:
                raise ValidationError("Potential match does not exist.")
            case = _row(db.execute("SELECT * FROM cases WHERE case_id = ?", (match["case_id"],)).fetchone())
            self._assert_case_access(user, case or {})
            if match["status"] != "PENDING":
                raise ValidationError("Only a PENDING potential match may be reviewed. Terminal decisions are preserved.")
            status = action_map[action]
            db.execute("UPDATE potential_matches SET status = ?, reviewed_at = ?, reviewed_by = ?, review_notes = ? WHERE id = ?",
                (status, _now(), actor, notes.strip(), match_id))
            result = _row(db.execute("SELECT * FROM potential_matches WHERE id = ?", (match_id,)).fetchone())
        self._audit(user, {"VERIFY": "MATCH_VERIFIED", "REJECT": "MATCH_REJECTED", "KEEP_PENDING": "MATCH_REMAINED_PENDING"}[action], "potential_match", str(match_id), {"from": match["status"], "to": status})
        if action in {"VERIFY", "REJECT"}:
            self._dispatch_notification_event(match_id, status)
        return result  # type: ignore[return-value]

    def list_matches(self, actor: str, case_id: str | None = None) -> list[dict[str, Any]]:
        user = self._require(actor, "view_parent_match", allow_any={"view_internal", "manage_cases", "review_matches"})
        query = "SELECT m.* FROM potential_matches m JOIN cases c ON c.case_id=m.case_id"
        params: list[Any] = []
        if case_id:
            query += " WHERE m.case_id = ?"
            params.append(case_id)
        query += " ORDER BY m.created_at DESC"
        with self._connection() as db:
            matches = [_row(row) for row in db.execute(query, params)]
        result = []
        for match in matches:
            if not match:
                continue
            case = self._case_for(match["case_id"])
            if case and self._case_allowed(user, case):
                result.append(self._parent_safe_match(match) if user["role"] == "PARENT" else match)
        return result

    def list_matches_for_user(self, user_id: int, case_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_matches(self._active_user_by_id(user_id)["username"], case_id)

    def get_evidence(self, actor: str, match_id: int) -> dict[str, Any] | None:
        user = self._require(actor, "view_internal", allow_any={"manage_cases", "review_matches"})
        with self._connection() as db:
            evidence = _row(db.execute("SELECT e.*, m.case_id FROM evidence e JOIN potential_matches m ON m.id=e.match_id WHERE e.match_id = ?", (match_id,)).fetchone())
        if evidence:
            case = self._case_for(evidence["case_id"])
            self._assert_case_access(user, case or {})
            self._audit(user, "EVIDENCE_VIEWED", "evidence", str(evidence["id"]), {"case_id": evidence["case_id"], "match_id": match_id})
        return evidence

    def mark_evidence_deleted(self, actor: str, evidence_id: int, reason: str, explicitly_confirmed: bool = False) -> None:
        """Controlled logical deletion; never deletes files automatically."""
        administrator = self._require(actor, "manage_users")
        if not explicitly_confirmed or not reason.strip():
            raise ValidationError("Explicit confirmation and a reason are required to delete evidence.")
        with self._connection() as db:
            evidence = _row(db.execute("SELECT e.*, m.case_id FROM evidence e JOIN potential_matches m ON m.id=e.match_id WHERE e.id=?", (int(evidence_id),)).fetchone())
            if not evidence:
                raise ValidationError("Evidence does not exist.")
            if evidence.get("legal_hold"):
                raise AuthorizationError("Evidence under legal hold cannot be deleted.")
            db.execute("UPDATE evidence SET evidence_status='DELETED', deleted_at=?, retention_note=?, deletion_reason=? WHERE id=?", (_now(), reason.strip()[:300], reason.strip()[:300], evidence_id))
        self._audit(administrator, "EVIDENCE_DELETED", "evidence", str(evidence_id), {"case_id": evidence["case_id"], "logical": True})

    def set_evidence_legal_hold(self, actor: str, evidence_id: int, enabled: bool, reason: str) -> None:
        admin = self._require(actor, "manage_users")
        if not reason.strip(): raise ValidationError("A legal-hold reason is required.")
        with self._connection() as db:
            if not db.execute("SELECT id FROM evidence WHERE id=?", (int(evidence_id),)).fetchone(): raise ValidationError("Evidence does not exist.")
            db.execute("UPDATE evidence SET legal_hold=?, retention_note=? WHERE id=?", (int(enabled), reason.strip()[:300], evidence_id))
        self._audit(admin, "EVIDENCE_LEGAL_HOLD_SET" if enabled else "EVIDENCE_LEGAL_HOLD_RELEASED", "evidence", str(evidence_id), {})

    def get_evidence_for_user(self, user_id: int, match_id: int) -> dict[str, Any] | None:
        return self.get_evidence(self._active_user_by_id(user_id)["username"], match_id)

    def evidence_display_path(self, actor: str, match_id: int) -> Path | None:
        """Resolve evidence only from the controlled alerts directory, never user input."""
        evidence = self.get_evidence(actor, match_id)
        if not evidence or not evidence.get("image_path"):
            return None
        name = self._safe_media_name(evidence["image_path"], IMAGE_EXTENSIONS)
        candidate = ALERTS_DIR / name
        return candidate if candidate.is_file() else None

    def set_encrypted_evidence_reference(self, match_id: int, reference: str) -> None:
        """System-only bridge for a newly encrypted controlled evidence file."""
        reference = self._safe_evidence_path(reference) or ""
        if not reference.endswith(".fernet"):
            raise ValidationError("Encrypted evidence reference is invalid.")
        with self._connection() as db:
            evidence = _row(db.execute("SELECT id FROM evidence WHERE match_id=?", (int(match_id),)).fetchone())
            if not evidence:
                raise ValidationError("Evidence does not exist.")
            db.execute("UPDATE evidence SET image_path=? WHERE id=?", (reference, evidence["id"]))
            db.execute("UPDATE potential_matches SET evidence_path=? WHERE id=?", (reference, int(match_id)))
        self._audit_system("EVIDENCE_ENCRYPTED", "potential_match", str(match_id), {"reference": reference})

    def submit_cctv(self, actor: str, case_id: str, station_location: str, filename: str, content: bytes, capture_datetime: str = "", description: str = "") -> dict[str, Any]:
        user = self._require(actor, "submit_cctv")
        case = self.get_case(actor, case_id)
        if not case:
            raise ValidationError("Case does not exist or is not available to this user.")
        if not self.case_allows_ai_processing(case_id):
            raise AuthorizationError("CCTV processing is blocked until police verification activates this case.")
        safe_name = self._safe_media_name(filename, VIDEO_EXTENSIONS)
        if not content or len(content) > MAX_CCTV_UPLOAD_BYTES:
            raise ValidationError("CCTV upload is empty or exceeds the configured file-size limit.")
        if not self._looks_like_video(safe_name, content):
            raise ValidationError("CCTV upload content does not match its declared video format.")
        CCTV_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4().hex}_{safe_name}"
        destination = CCTV_UPLOADS_DIR / stored_name
        destination.write_bytes(content)
        with self._connection() as db:
            cursor = db.execute("INSERT INTO cctv_submissions(case_id, station_location, uploading_user, stored_name, capture_datetime, description, processing_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING_PROCESSING', ?)",
                (case_id, station_location.strip(), actor, stored_name, capture_datetime.strip(), description.strip(), _now()))
            submission = _row(db.execute("SELECT * FROM cctv_submissions WHERE id = ?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "CCTV_SUBMITTED", "cctv_submission", str(submission["id"]), {"case_id": case_id, "status": "PENDING_PROCESSING"})
        return submission  # type: ignore[return-value]

    def assign_station(self, actor: str, case_id: str, station_code: str, status: str = "ACTIVE") -> dict[str, Any]:
        user = self._require(actor, "manage_cases")
        if status not in ASSIGNMENT_STATUSES:
            raise ValidationError("Station assignment status must be ACTIVE, PENDING, or CLOSED.")
        if not self._case_for(case_id):
            raise ValidationError("Case does not exist.")
        with self._connection() as db:
            db.execute("INSERT INTO case_station_assignments(case_id, station_code, assignment_status, assigned_at, assigned_by) VALUES (?, ?, ?, ?, ?) ON CONFLICT(case_id, station_code) DO UPDATE SET assignment_status=excluded.assignment_status, assigned_at=excluded.assigned_at, assigned_by=excluded.assigned_by", (case_id, self._identifier(station_code, "station code"), status, _now(), actor))
            assignment = _row(db.execute("SELECT * FROM case_station_assignments WHERE case_id=? AND station_code=?", (case_id, station_code)).fetchone())
        self._audit(user, "CASE_STATION_ASSIGNED", "case", case_id, {"station_code": station_code, "status": status})
        return assignment  # type: ignore[return-value]

    def list_station_assignments(self, actor: str, case_id: str) -> list[dict[str, Any]]:
        """Return station assignments only to staff authorized for the case."""
        user = self._require(actor, "manage_cases", allow_any={"view_internal", "review_matches"})
        case = self._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        self._assert_case_access(user, case)
        with self._connection() as db:
            return [_row(row) for row in db.execute("SELECT * FROM case_station_assignments WHERE case_id=? ORDER BY station_code", (case_id,))]

    def get_authorized_case_stations(self, case_id: str) -> list[str]:
        """Return only the owning station and explicitly active case assignments."""
        case = self._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        with self._connection() as db:
            assigned = [row[0] for row in db.execute("SELECT station_code FROM case_station_assignments WHERE case_id=? AND assignment_status='ACTIVE'", (case_id,))]
        return sorted({case["authorized_station"], *assigned})

    def notification_match_context(self, match_id: int) -> dict[str, Any]:
        """Trusted internal context for templates; never returned directly to a parent."""
        try:
            match_id = int(match_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Notification match ID is invalid.") from exc
        with self._connection() as db:
            context = _row(db.execute("""SELECT m.*, c.parent_username, c.authorized_station,
                (SELECT e.id FROM evidence e WHERE e.match_id=m.id ORDER BY e.id LIMIT 1) AS evidence_id
                FROM potential_matches m JOIN cases c ON c.case_id=m.case_id WHERE m.id=?""", (match_id,)).fetchone())
            observation = _row(db.execute("""SELECT o.observed_at, c.camera_id, c.camera_name, c.station_code
                FROM match_observations o JOIN cameras c ON c.camera_id=o.camera_id
                WHERE o.match_id=? ORDER BY o.observed_at DESC LIMIT 1""", (match_id,)).fetchone())
        if not context:
            raise ValidationError("Potential match does not exist.")
        context["last_observed"] = observation
        return context

    def list_notifications(self, actor: str) -> list[dict[str, Any]]:
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
        with self._connection() as db:
            if user["role"] == "ADMIN":
                rows = db.execute("SELECT * FROM notifications ORDER BY created_at DESC").fetchall()
            else:
                rows = db.execute("SELECT * FROM notifications WHERE recipient_user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
        return [_row(row) for row in rows]

    def list_notifications_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return self.list_notifications(self._active_user_by_id(user_id)["username"])

    def mark_notification_read(self, actor: str, notification_id: int) -> dict[str, Any]:
        user = self._require(actor, "view_own_case", allow_any={"view_internal", "manage_cases", "review_matches", "view_audit"})
        try:
            notification_id = int(notification_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Notification ID is invalid.") from exc
        with self._connection() as db:
            notification = _row(db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone())
            if not notification:
                raise ValidationError("Notification does not exist.")
            if user["role"] != "ADMIN" and notification["recipient_user_id"] != user["id"]:
                raise AuthorizationError("This notification is not available to the selected user.")
            if notification["status"] not in {"READ", "FAILED", "CANCELLED"}:
                db.execute("UPDATE notifications SET status='READ', read_at=? WHERE id=?", (_now(), notification_id))
            updated = _row(db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone())
        self._audit(user, "NOTIFICATION_READ", "notification", str(notification_id), {"case_id": notification["case_id"]})
        return updated  # type: ignore[return-value]

    def record_match_observation(self, actor: str, match_id: int, camera_id: str, observed_at: str | None = None) -> dict[str, Any]:
        """Record an existing registered camera observation; this is not GPS tracking."""
        user = self._require(actor, "manage_cases", allow_any={"review_matches"})
        context = self.notification_match_context(match_id)
        self._assert_case_access(user, self._case_for(context["case_id"]) or {})
        camera_id = self._identifier(camera_id, "camera ID")
        with self._connection() as db:
            camera = _row(db.execute("SELECT * FROM cameras WHERE camera_id=? AND active=1", (camera_id,)).fetchone())
            if not camera or camera["station_code"] not in self.get_authorized_case_stations(context["case_id"]):
                raise AuthorizationError("Camera is not an authorized active camera for this case.")
            timestamp = observed_at or _now()
            try:
                cursor = db.execute("INSERT INTO match_observations(match_id, camera_id, observed_at, created_at) VALUES (?, ?, ?, ?)", (int(match_id), camera_id, timestamp, _now()))
            except sqlite3.IntegrityError as exc:
                raise ValidationError("This camera observation already exists.") from exc
            observation = _row(db.execute("SELECT * FROM match_observations WHERE id=?", (cursor.lastrowid,)).fetchone())
        self._audit(user, "MATCH_OBSERVATION_RECORDED", "potential_match", str(match_id), {"case_id": context["case_id"], "camera_id": camera_id})
        return observation  # type: ignore[return-value]

    def register_camera(self, actor: str, data: dict[str, Any]) -> dict[str, Any]:
        self._require(actor, "manage_cases")
        camera_id = self._identifier(str(data.get("camera_id", "")), "camera ID")
        latitude, longitude = data.get("latitude"), data.get("longitude")
        if latitude is not None and (not self._coordinate(latitude, -90, 90) or not self._coordinate(longitude, -180, 180)):
            raise ValidationError("Camera latitude/longitude must be valid coordinates when provided.")
        with self._connection() as db:
            db.execute("INSERT INTO cameras(camera_id, station_code, camera_name, latitude, longitude, location_description, active) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(camera_id) DO UPDATE SET station_code=excluded.station_code, camera_name=excluded.camera_name, latitude=excluded.latitude, longitude=excluded.longitude, location_description=excluded.location_description, active=excluded.active", (camera_id, self._identifier(str(data.get("station_code", "")), "station code"), str(data.get("camera_name", "")).strip() or "Unnamed camera", latitude, longitude, str(data.get("location_description", "")).strip(), int(bool(data.get("active", True)))))
            camera = _row(db.execute("SELECT * FROM cameras WHERE camera_id=?", (camera_id,)).fetchone())
        return camera  # type: ignore[return-value]

    def metrics(self, actor: str) -> dict[str, int]:
        cases = self.list_cases(actor)
        matches = self.list_matches(actor)
        return {"active_cases": sum(case["case_status"] == "ACTIVE" for case in cases), "potential_matches": len(matches), "pending_reviews": sum(match["status"] == "PENDING" for match in matches), "verified_matches": sum(match["status"] == "VERIFIED" for match in matches), "rejected_matches": sum(match["status"] == "REJECTED" for match in matches), "cctv_runs": self._count_runs(cases)}

    def list_audit_logs(self, actor: str) -> list[dict[str, Any]]:
        self._require(actor, "view_audit")
        with self._connection() as db:
            return [_row(row) for row in db.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC, id DESC")]

    def _audit(self, user: dict[str, Any], action: str, resource_type: str, resource_id: str, details: dict[str, Any], outcome: str = "SUCCESS") -> None:
        with self._connection() as db:
            db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user["id"], user["role"], action, resource_type, resource_id, _now(), self._json_text(details), outcome))

    def _audit_system(self, action: str, resource_type: str, resource_id: str, details: dict[str, Any]) -> None:
        """Log a non-human pipeline event without inventing a user identity."""
        with self._connection() as db:
            db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (None, "SYSTEM", action, resource_type, resource_id, _now(), self._json_text(details), "SUCCESS"))

    def _dispatch_notification_event(self, match_id: int, event: str) -> None:
        """Keep a notification-provider failure visible without changing review state."""
        try:
            from .notification_service import NotificationService
            NotificationService(self).notify_match_event(match_id, event)
        except Exception as exc:
            self._audit_system("NOTIFICATION_FAILED", "potential_match", str(match_id), {"event": event, "reason": str(exc)[:300]})

    def _require(self, actor: str, permission: str, allow_any: set[str] | None = None) -> dict[str, Any]:
        user = self.get_user(actor)
        if not user or not user.get("is_active", 1):
            raise AuthorizationError("Select a valid local prototype user.")
        permissions = ROLE_PERMISSIONS[user["role"]]
        if permission not in permissions and not (allow_any and permissions.intersection(allow_any)):
            raise AuthorizationError("This role is not permitted to perform that action.")
        return user

    def _active_user_by_id(self, user_id: int) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if not user or not user.get("is_active", 1):
            raise AuthorizationError("Your session is no longer authorized. Please sign in again.")
        return user

    def _validate_case(self, data: dict[str, Any]) -> dict[str, Any]:
        case_id = self._identifier(str(data.get("case_id", "")), "case ID")
        child_id = self._identifier(str(data.get("child_id", "")), "child ID")
        child_name = str(data.get("child_name", "")).strip()
        description = str(data.get("description", "")).strip()
        if not child_name or not description:
            raise ValidationError("Case requires child name and description.")
        age = data.get("age")
        if age not in (None, "") and (not isinstance(age, int) or isinstance(age, bool) or age < 0):
            raise ValidationError("Age must be a non-negative whole number when provided.")
        reference_image = self._safe_media_name(str(data.get("reference_image", "")), IMAGE_EXTENSIONS)
        status = data.get("case_status", "ACTIVE")
        if status not in CASE_STATUSES:
            raise ValidationError("Case status must be DRAFT, ACTIVE, PAUSED, UNDER_REVIEW, RESOLVED, CLOSED, or ARCHIVED.")
        station = self._identifier(str(data.get("authorized_station", "")), "authorized station")
        return {"case_id": case_id, "child_id": child_id, "child_name": child_name, "age": age or None, "description": description, "reference_image": reference_image, "case_status": status, "authorized_station": station, "region": str(data.get("region", "")).strip() or None, "station_code": str(data.get("station_code", station)).strip(), "parent_username": str(data.get("parent_username", "")).strip() or None}

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        try:
            safe_filename(value)
        except ValueError as exc:
            raise ValidationError(f"{label.capitalize()} must be a simple identifier, not a path.") from exc
        return value

    @staticmethod
    def _safe_media_name(value: str, allowed_extensions: set[str]) -> str:
        try:
            name = safe_filename(value)
        except ValueError as exc:
            raise ValidationError("File name must not contain a path.") from exc
        if any(marker in name.lower() for marker in ("%2e", "%2f", "%5c")):
            raise ValidationError("File name must not contain encoded path traversal.")
        if Path(name).suffix.lower() not in allowed_extensions:
            raise ValidationError(f"Unsupported file type. Allowed: {', '.join(sorted(allowed_extensions))}.")
        return name

    @staticmethod
    def _safe_evidence_path(value: Any) -> str | None:
        if not value:
            return None
        candidate = Path(str(value))
        if candidate.suffix.lower() not in IMAGE_EXTENSIONS | {".json", ".fernet"}:
            raise ValidationError("Evidence reference is invalid.")
        return candidate.name

    @staticmethod
    def _json_text(value: Any) -> str:
        def redact(item: Any) -> Any:
            if isinstance(item, dict):
                return {str(key): "[REDACTED]" if any(word in str(key).lower() for word in ("password", "secret", "token", "api_key", "hash")) else redact(value) for key, value in item.items()}
            if isinstance(item, list):
                return [redact(value) for value in item]
            return item
        cleaned = redact(value)
        return json.dumps(cleaned, sort_keys=True) if isinstance(cleaned, (dict, list)) else str(cleaned)

    @staticmethod
    def _email(value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValidationError("Email must be a valid address.")
        return normalized

    @staticmethod
    def _looks_like_video(filename: str, content: bytes) -> bool:
        extension = Path(filename).suffix.lower()
        if extension == ".avi":
            return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"AVI "
        if extension == ".mp4":
            return len(content) >= 12 and content[4:8] == b"ftyp"
        if extension == ".mov":
            return len(content) >= 12 and content[4:8] == b"ftyp"
        return False

    def validate_reference_upload(self, filename: str, content: bytes) -> str:
        """Validate image type, bounded bytes, and a lightweight image signature."""
        safe_name = self._safe_media_name(filename, IMAGE_EXTENSIONS)
        if not content or len(content) > MAX_REFERENCE_IMAGE_BYTES:
            raise ValidationError("Reference image is empty or exceeds the configured file-size limit.")
        suffix = Path(safe_name).suffix.lower()
        jpeg = len(content) >= 3 and content[:3] == b"\xff\xd8\xff"
        png = len(content) >= 8 and content[:8] == b"\x89PNG\r\n\x1a\n"
        if (suffix in {".jpg", ".jpeg"} and not jpeg) or (suffix == ".png" and not png):
            raise ValidationError("Reference image content does not match its declared format.")
        return safe_name

    @staticmethod
    def _locked(user: dict[str, Any]) -> bool:
        value = user.get("lockout_until")
        if not value:
            return False
        try:
            return datetime.fromisoformat(value) > datetime.now(timezone.utc)
        except ValueError:
            return True

    def _audit_login_failure(self, db: sqlite3.Connection, user: dict[str, Any] | None, identity: str) -> None:
        if user:
            failures = int(user.get("failed_login_count") or 0) + 1
            lockout = None
            if failures >= LOGIN_MAX_FAILURES:
                from datetime import timedelta
                lockout = (datetime.now(timezone.utc) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).isoformat()
            db.execute("UPDATE users SET failed_login_count=?, lockout_until=? WHERE id=?", (failures, lockout, user["id"]))
            db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user["id"], user["role"], "LOGIN_FAILURE", "authentication", str(user["id"]), _now(), self._json_text({"identity": identity}), "FAILURE"))
        else:
            db.execute("INSERT INTO audit_logs(user_id, role, action, resource_type, resource_id, timestamp, details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (None, None, "LOGIN_FAILURE", "authentication", "unknown", _now(), self._json_text({"identity": identity}), "FAILURE"))

    @staticmethod
    def _coordinate(value: Any, lower: float, upper: float) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and lower <= value <= upper

    def _case_for(self, case_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            return _row(db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone())

    def _case_allowed(self, user: dict[str, Any], case: dict[str, Any]) -> bool:
        if user["role"] == "ADMIN":
            return True
        if user["role"] == "PARENT":
            return case.get("parent_username") == user["username"]
        return not user.get("station") or user["station"] in self.get_authorized_case_stations(case["case_id"])

    def _assert_case_access(self, user: dict[str, Any], case: dict[str, Any]) -> None:
        if not self._case_allowed(user, case):
            raise AuthorizationError("This case is not available to the selected user.")

    @staticmethod
    def _parent_safe_case(case: dict[str, Any]) -> dict[str, Any]:
        state = case.get("lifecycle_state") or case.get("case_status")
        safe_status = "Case active" if state == "ACTIVE" else "Awaiting police verification" if state == "PENDING_POLICE_VERIFICATION" else "Report submitted"
        result = {key: case.get(key) for key in ("case_id", "child_id", "child_name", "case_status", "created_at", "updated_at")}
        result.update({"lifecycle_state": state, "police_verification_status": safe_status})
        return result

    @staticmethod
    def _parent_safe_match(match: dict[str, Any]) -> dict[str, Any]:
        return {key: match[key] for key in ("id", "case_id", "child_id", "status", "created_at", "reviewed_at")}

    def _count_runs(self, cases: list[dict[str, Any]]) -> int:
        case_ids = [case["case_id"] for case in cases]
        if not case_ids:
            return 0
        placeholders = ",".join("?" for _ in case_ids)
        with self._connection() as db:
            return int(db.execute(f"SELECT COUNT(DISTINCT run_id) FROM potential_matches WHERE case_id IN ({placeholders})", case_ids).fetchone()[0])
