import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.auth import build_session, session_expired
from services.retention import RetentionService
from services.review_store import AuthorizationError, ReviewStore, ValidationError


class Sprint5SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.temp.name) / "secure.db")
        self.store.initialize()
        self.store.create_user("admin", "ADMIN", "HQ", password="correct-horse-battery-staple", email="admin@example.test")
        self.store.create_user("police", "POLICE", "HQ", password="correct-horse-battery-staple", email="police@example.test", actor="admin")
        self.store.create_user("reviewer", "REVIEWER", "HQ", password="correct-horse-battery-staple", email="reviewer@example.test", actor="admin")
        self.store.create_user("parent", "PARENT", password="correct-horse-battery-staple", email="parent@example.test", actor="admin")
        self.store.create_user("other_parent", "PARENT", password="correct-horse-battery-staple", email="other@example.test", actor="admin")
        self.store.create_case("police", {"case_id": "CASE001", "child_id": "MC001", "child_name": "Child", "description": "Description", "reference_image": "child1.jpeg", "authorized_station": "HQ", "parent_username": "parent"})

    def tearDown(self):
        self.temp.cleanup()

    def _match(self):
        return self.store.record_potential_match({"case_id": "CASE001", "child_id": "MC001", "track_id": 1, "run_id": "run-1", "frame_number": 1, "video_name": "station.mp4", "evidence_path": "match.jpg", "metadata_path": "match.json"})

    def test_argon2_hash_does_not_store_plaintext_and_login_succeeds(self):
        user = self.store.get_user("admin")
        self.assertNotEqual(user["password_hash"], "correct-horse-battery-staple")
        authenticated = self.store.authenticate("admin@example.test", "correct-horse-battery-staple")
        self.assertEqual(authenticated["username"], "admin")

    def test_existing_sprint4_user_can_be_safely_bootstrapped_when_no_credentials_exist(self):
        legacy = ReviewStore(Path(self.temp.name) / "legacy.db")
        legacy.initialize()
        legacy.create_user("legacy_admin", "ADMIN", "HQ")
        migrated = legacy.bootstrap_admin("legacy_admin", "legacy@example.test", "correct-horse-battery-staple")
        self.assertEqual(migrated["role"], "ADMIN")
        self.assertTrue(migrated["password_hash"])
        self.assertEqual(legacy.authenticate("legacy_admin", "correct-horse-battery-staple")["username"], "legacy_admin")

    def test_existing_sprint4_database_schema_is_migrated_without_data_deletion(self):
        legacy_path = Path(self.temp.name) / "pre_sprint5.db"
        import sqlite3
        database = sqlite3.connect(legacy_path)
        database.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL, station TEXT, created_at TEXT NOT NULL)")
        database.execute("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, timestamp TEXT NOT NULL, details TEXT)")
        database.execute("INSERT INTO users(username, role, station, created_at) VALUES ('legacy', 'ADMIN', 'HQ', '2026-01-01T00:00:00+00:00')")
        database.commit()
        database.close()
        migrated = ReviewStore(legacy_path)
        migrated.initialize()
        self.assertTrue(migrated.get_user("legacy"))
        with migrated._connection() as database:
            columns = {row[1] for row in database.execute("PRAGMA table_info(users)")}
        self.assertTrue({"password_hash", "is_active", "failed_login_count", "lockout_until"}.issubset(columns))

    def test_invalid_login_is_generic_and_rate_limited(self):
        with patch("services.review_store.LOGIN_MAX_FAILURES", 2):
            self.assertIsNone(self.store.authenticate("admin", "wrong-password"))
            self.assertIsNone(self.store.authenticate("admin", "wrong-password"))
        user = self.store.get_user("admin")
        self.assertTrue(user["lockout_until"])
        self.assertIsNone(self.store.authenticate("admin", "correct-horse-battery-staple"))
        self.assertIn("LOGIN_FAILURE", [row["action"] for row in self.store.list_audit_logs("admin")])

    def test_inactive_user_cannot_authenticate_and_session_expires(self):
        self.store.deactivate_user("admin", "reviewer", False)
        self.assertIsNone(self.store.authenticate("reviewer", "correct-horse-battery-staple"))
        session = build_session(self.store.get_user("admin"))
        session["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
        self.assertTrue(session_expired(session, timeout_minutes=30))

    def test_logout_and_sensitive_audit_details_do_not_keep_secrets(self):
        admin = self.store.authenticate("admin", "correct-horse-battery-staple")
        self.store.record_logout(admin["id"])
        self.store._audit(admin, "TEST", "security", "test", {"password": "hidden", "api_key": "hidden", "safe": "kept"})
        details = self.store.list_audit_logs("admin")[0]["details"]
        self.assertNotIn("hidden", details)
        self.assertIn("[REDACTED]", details)
        self.assertIn("LOGOUT", [row["action"] for row in self.store.list_audit_logs("admin")])

    def test_parent_isolation_evidence_and_malicious_sql_attempt(self):
        match = self._match()
        self.assertEqual(self.store.list_cases("other_parent"), [])
        with self.assertRaises(AuthorizationError):
            self.store.get_evidence_for_user(self.store.get_user("parent")["id"], match["id"])
        self.assertIsNone(self.store.authenticate("admin' OR 1=1 --", "anything"))
        self.assertIn("POTENTIAL_MATCH_CREATED", [row["action"] for row in self.store.list_audit_logs("admin")])

    def test_admin_only_user_management_and_reviewer_review_access(self):
        with self.assertRaises(AuthorizationError):
            self.store.create_user("not_allowed", "PARENT", password="correct-horse-battery-staple", actor="police")
        match = self._match()
        self.assertEqual(self.store.review_match("reviewer", match["id"], "KEEP_PENDING", "More review")["status"], "PENDING")

    def test_secure_upload_rejects_traversal_encoded_paths_and_bad_content(self):
        with self.assertRaisesRegex(ValidationError, "File name"):
            self.store.submit_cctv("police", "CASE001", "HQ", "..\\unsafe.mp4", b"0000ftypisom")
        with self.assertRaisesRegex(ValidationError, "encoded"):
            self.store.submit_cctv("police", "CASE001", "HQ", "%2e%2e.mp4", b"0000ftypisom")
        with self.assertRaisesRegex(ValidationError, "content"):
            self.store.submit_cctv("police", "CASE001", "HQ", "station.mp4", b"not-a-video")
        submission = self.store.submit_cctv("police", "CASE001", "HQ", "station.mp4", b"0000ftypisom")
        self.assertEqual(submission["processing_status"], "PENDING_PROCESSING")
        self.assertNotEqual(submission["stored_name"], "station.mp4")

    def test_retention_is_dry_run_by_default(self):
        match = self._match()
        with self.store._connection() as db:
            db.execute("UPDATE evidence SET created_at=? WHERE match_id=?", ((datetime.now(timezone.utc) - timedelta(days=31)).isoformat(), match["id"]))
        report = RetentionService(self.store).report("admin")
        self.assertTrue(report["dry_run"])
        self.assertEqual(len(report["expired_evidence"]), 1)
        result = RetentionService(self.store).apply("admin", explicitly_enabled=False)
        self.assertEqual(result["deleted_evidence"], 0)

    def test_terminal_review_transition_and_evidence_path_traversal_rejected(self):
        match = self._match()
        self.store.review_match("reviewer", match["id"], "REJECT", "Not the child")
        with self.assertRaisesRegex(ValidationError, "Only a PENDING"):
            self.store.review_match("reviewer", match["id"], "VERIFY", confirmed=True)
        with self.assertRaisesRegex(ValidationError, "Evidence reference"):
            self.store.record_potential_match({"case_id": "CASE001", "child_id": "MC001", "track_id": 2, "run_id": "run-1", "frame_number": 2, "video_name": "station.mp4", "evidence_path": "../secret.txt"})
