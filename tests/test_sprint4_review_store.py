import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.review_store import AuthorizationError, ReviewStore, ValidationError


class Sprint4ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.temp.name) / "missing_child_ai.db")
        self.store.initialize()
        self.store.create_user("admin", "ADMIN", "HQ")
        self.store.create_user("police_hq", "POLICE", "HQ")
        self.store.create_user("police_other", "POLICE", "OTHER")
        self.store.create_user("reviewer", "REVIEWER", "HQ")
        self.store.create_user("parent_a", "PARENT")
        self.store.create_user("parent_b", "PARENT")
        self.case = self.store.create_case("police_hq", {
            "case_id": "CASE001", "child_id": "MC001", "child_name": "Example Child",
            "age": 10, "description": "Blue shirt", "reference_image": "child1.jpeg",
            "authorized_station": "HQ", "parent_username": "parent_a",
        })

    def tearDown(self):
        self.temp.cleanup()

    def _match(self):
        return self.store.record_potential_match({
            "case_id": "CASE001", "child_id": "MC001", "track_id": 12,
            "run_id": "run-001", "frame_number": 120, "video_name": "station.mp4",
            "face_score": 84.0, "overall_score": 80.0,
            "reason": {"matched": ["clothing.top_color"], "unknown": ["accessories.glasses"]},
            "evidence_path": "MC001_track_12.jpg", "metadata_path": "MC001_track_12.json",
        })

    def test_database_schema_and_case_creation(self):
        self.assertTrue(self.store.database_path.is_file())
        self.assertEqual(self.case["case_status"], "ACTIVE")
        self.assertEqual(self.store.list_cases("police_hq")[0]["case_id"], "CASE001")

    def test_duplicate_case_and_invalid_case_are_rejected(self):
        with self.assertRaisesRegex(ValidationError, "already exists"):
            self.store.create_case("police_hq", {"case_id": "CASE001", "child_id": "MC002", "child_name": "Other", "description": "desc", "reference_image": "child1.jpeg", "authorized_station": "HQ"})
        with self.assertRaisesRegex(ValidationError, "Unsupported file type"):
            self.store.create_case("police_hq", {"case_id": "CASE002", "child_id": "MC002", "child_name": "Other", "description": "desc", "reference_image": "bad.exe", "authorized_station": "HQ"})

    def test_case_update_is_audited_and_path_traversal_is_rejected(self):
        updated = self.store.update_case("police_hq", "CASE001", {"case_status": "PAUSED"})
        self.assertEqual(updated["case_status"], "PAUSED")
        with self.assertRaisesRegex(ValidationError, "not a path"):
            self.store.create_case("police_hq", {"case_id": "../CASE002", "child_id": "MC002", "child_name": "Other", "description": "desc", "reference_image": "child1.jpeg", "authorized_station": "HQ"})

    def test_pending_match_and_explicit_review_transitions(self):
        match = self._match()
        self.assertEqual(match["status"], "PENDING")
        with self.assertRaisesRegex(ValidationError, "explicit confirmation"):
            self.store.review_match("reviewer", match["id"], "VERIFY")
        verified = self.store.review_match("reviewer", match["id"], "VERIFY", "Reviewed evidence", confirmed=True)
        self.assertEqual(verified["status"], "VERIFIED")
        with self.assertRaisesRegex(ValidationError, "Only a PENDING"):
            self.store.review_match("reviewer", match["id"], "REJECT", "False candidate")
        rejected_match = self.store.record_potential_match({"case_id": "CASE001", "child_id": "MC001", "track_id": 13, "run_id": "run-001", "frame_number": 121, "video_name": "station.mp4"})
        rejected = self.store.review_match("reviewer", rejected_match["id"], "REJECT", "False candidate")
        self.assertEqual(rejected["status"], "REJECTED")
        with self.assertRaisesRegex(ValidationError, "KEEP_PENDING"):
            self.store.review_match("reviewer", match["id"], "FOUND")

    def test_duplicate_match_and_invalid_evidence_reference_are_rejected(self):
        self._match()
        with self.assertRaisesRegex(ValidationError, "already exists"):
            self._match()
        with self.assertRaisesRegex(ValidationError, "Evidence reference"):
            self.store.record_potential_match({"case_id": "CASE001", "child_id": "MC001", "track_id": 13, "run_id": "run-001", "frame_number": 121, "video_name": "station.mp4", "evidence_path": "unsafe.exe"})

    def test_audit_log_created_for_case_and_review(self):
        match = self._match()
        self.store.review_match("reviewer", match["id"], "KEEP_PENDING", "Need another view")
        actions = [row["action"] for row in self.store.list_audit_logs("admin")]
        self.assertIn("CASE_CREATED", actions)
        self.assertIn("MATCH_REMAINED_PENDING", actions)

    def test_login_is_audited(self):
        self.store.record_login("reviewer")
        self.assertIn("LOGIN", [row["action"] for row in self.store.list_audit_logs("admin")])

    def test_parent_isolation_and_internal_access(self):
        self._match()
        parent_cases = self.store.list_cases("parent_a")
        self.assertEqual(len(parent_cases), 1)
        self.assertNotIn("description", parent_cases[0])
        self.assertEqual(self.store.list_cases("parent_b"), [])
        parent_match = self.store.list_matches("parent_a")[0]
        self.assertNotIn("face_score", parent_match)
        self.assertEqual(len(self.store.list_matches("police_hq")), 1)
        self.assertEqual(self.store.list_matches("police_other"), [])
        self.assertEqual(len(self.store.list_matches("reviewer")), 1)

    def test_evidence_is_staff_only_and_paths_are_not_exposed_as_supplied(self):
        match = self._match()
        evidence = self.store.get_evidence("reviewer", match["id"])
        self.assertEqual(evidence["image_path"], "MC001_track_12.jpg")
        with self.assertRaises(AuthorizationError):
            self.store.get_evidence("parent_a", match["id"])
        with self.assertRaises(AuthorizationError):
            self.store.get_evidence("police_other", match["id"])

    def test_cctv_upload_extension_and_size_are_validated(self):
        with self.assertRaisesRegex(ValidationError, "Unsupported file type"):
            self.store.submit_cctv("police_hq", "CASE001", "HQ", "unsafe.exe", b"x")
        with patch("services.review_store.MAX_CCTV_UPLOAD_BYTES", 3):
            with self.assertRaisesRegex(ValidationError, "file-size"):
                self.store.submit_cctv("police_hq", "CASE001", "HQ", "station.mp4", b"1234")

    def test_station_assignment_and_camera_validation(self):
        assignment = self.store.assign_station("police_hq", "CASE001", "HQ", "ACTIVE")
        self.assertEqual(assignment["assignment_status"], "ACTIVE")
        with self.assertRaisesRegex(ValidationError, "assignment status"):
            self.store.assign_station("police_hq", "CASE001", "HQ", "INVALID")
        camera = self.store.register_camera("police_hq", {"camera_id": "CAM001", "station_code": "HQ", "camera_name": "Gate", "latitude": 12.97, "longitude": 80.2, "active": True})
        self.assertEqual(camera["camera_id"], "CAM001")
        with self.assertRaisesRegex(ValidationError, "coordinates"):
            self.store.register_camera("police_hq", {"camera_id": "CAM002", "station_code": "HQ", "camera_name": "Bad", "latitude": 100, "longitude": 80})
