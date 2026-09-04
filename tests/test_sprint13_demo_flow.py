"""Sprint 13 — UI/service integration tests for the end-to-end demo flow.

Tests validate service-layer boundaries that the new Streamlit pages rely on.
They do not invoke AI models (YOLO/DeepSORT/InsightFace) or require a GPU.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Minimal image bytes for upload validation ──────────────────────────────────
_JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 100
_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_MP4_HEADER = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100


def _make_store(tmp_dir: Path):
    """Return a fresh ReviewStore backed by a temp database."""
    from services.review_store import ReviewStore

    db_path = tmp_dir / "test_s13.db"
    store = ReviewStore(database_path=db_path)
    store.initialize()
    return store


def _bootstrap(store, tmp_dir: Path):
    """Create the minimum accounts needed for sprint 13 tests."""
    store.bootstrap_admin("admin_s13", "admin@demo.local", "AdminPass!13")
    store.create_user("police_s13", "POLICE", station="HQ", password="PolicePass!13", actor="admin_s13")
    store.create_user("reviewer_s13", "REVIEWER", password="ReviewPass!13", actor="admin_s13")
    store.create_user("parent_s13", "PARENT", password="ParentPass!13", actor="admin_s13")
    return store


class TestParentReportWorkflow(unittest.TestCase):
    """Parent creates a report; verifies it cannot activate case."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parent_can_create_preliminary_report(self):
        report = self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE013",
                "child_id": "MC013",
                "child_name": "Demo Child",
                "age": 8,
                "description": "Sprint 13 test child",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "last_seen_location": "Park Street",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        self.assertEqual(report["case_id"], "CASE013")
        self.assertEqual(report["lifecycle_state"], "PENDING_POLICE_VERIFICATION")

    def test_report_begins_as_pending_police_verification(self):
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE013B",
                "child_id": "MC013B",
                "child_name": "Demo Child B",
                "age": 6,
                "description": "Test case",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        case = self.store.get_case("parent_s13", "CASE013B")
        self.assertIsNotNone(case)
        self.assertEqual(case["lifecycle_state"], "PENDING_POLICE_VERIFICATION")

    def test_parent_cannot_activate_case(self):
        from services.review_store import AuthorizationError

        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE013C",
                "child_id": "MC013C",
                "child_name": "Demo Child C",
                "age": 7,
                "description": "Test case",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.verify_police_complaint(
                "parent_s13", "CASE013C", "FIR001", "2024-01-01", "HQ"
            )

    def test_parent_cannot_access_another_parent_case(self):
        from services.review_store import AuthorizationError

        self.store.create_user("parent2_s13", "PARENT", password="ParentTwo!13", actor="admin_s13")
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE013D",
                "child_id": "MC013D",
                "child_name": "Demo Child D",
                "age": 9,
                "description": "Test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.get_case("parent2_s13", "CASE013D")

    def test_parent_can_upload_child_photo_via_validate(self):
        # validate_reference_upload does not require an active case
        name = self.store.validate_reference_upload("child.jpeg", _JPEG_HEADER)
        self.assertEqual(name, "child.jpeg")

    def test_parent_png_upload_accepted(self):
        name = self.store.validate_reference_upload("photo.png", _PNG_HEADER)
        self.assertEqual(name, "photo.png")


class TestPoliceWorkflow(unittest.TestCase):
    """Police can see pending complaints and verify them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_pending_case(self, case_id="CASE014", child_id="MC014"):
        return self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": case_id,
                "child_id": child_id,
                "child_name": "Demo Child",
                "age": 10,
                "description": "Police test case",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "FIR001",
            },
        )

    def test_police_can_see_pending_complaints(self):
        self._create_pending_case()
        cases = self.store.list_cases("police_s13")
        pending = [
            c for c in cases
            if (c.get("lifecycle_state") or c.get("case_status")) == "PENDING_POLICE_VERIFICATION"
        ]
        self.assertGreater(len(pending), 0)

    def test_police_can_verify_complaint(self):
        self._create_pending_case("CASE014V", "MC014V")
        result = self.store.verify_police_complaint(
            "police_s13", "CASE014V", "FIR002", "2024-01-01", "HQ", "Verified in test."
        )
        self.assertEqual(result["lifecycle_state"], "ACTIVE")
        self.assertEqual(result["case_status"], "ACTIVE")

    def test_verification_changes_lifecycle_to_active(self):
        self._create_pending_case("CASE014A", "MC014A")
        self.store.verify_police_complaint(
            "police_s13", "CASE014A", "FIR003", "2024-01-02", "HQ"
        )
        case = self.store.get_case("police_s13", "CASE014A")
        self.assertEqual((case.get("lifecycle_state") or case.get("case_status")), "ACTIVE")

    def test_police_action_is_audited(self):
        self._create_pending_case("CASE014B", "MC014B")
        self.store.verify_police_complaint(
            "police_s13", "CASE014B", "FIR004", "2024-01-03", "HQ"
        )
        logs = self.store.list_audit_logs("admin_s13")
        actions = [log["action"] for log in logs if log]
        self.assertIn("POLICE_COMPLAINT_VERIFIED", actions)

    def test_inactive_case_cannot_start_cctv_processing(self):
        self._create_pending_case("CASE014C", "MC014C")
        can_process = self.store.case_allows_ai_processing("CASE014C")
        self.assertFalse(can_process)

    def test_active_case_allows_ai_processing(self):
        self._create_pending_case("CASE014D", "MC014D")
        self.store.verify_police_complaint(
            "police_s13", "CASE014D", "FIR005", "2024-01-04", "HQ"
        )
        can_process = self.store.case_allows_ai_processing("CASE014D")
        self.assertTrue(can_process)


class TestCCTVUploadWorkflow(unittest.TestCase):
    """CCTV upload validation and authorization boundary."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        # Patch CCTV_UPLOADS_DIR to use temp dir
        import services.review_store as rs

        self._orig_uploads = rs.CCTV_UPLOADS_DIR
        rs.CCTV_UPLOADS_DIR = self.tmp_path / "cctv_uploads"
        rs.CCTV_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)

    def tearDown(self):
        import services.review_store as rs

        rs.CCTV_UPLOADS_DIR = self._orig_uploads
        self.tmp.cleanup()

    def _active_case(self, case_id="CASE015", child_id="MC015"):
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": case_id,
                "child_id": child_id,
                "child_name": "CCTV Test Child",
                "age": 11,
                "description": "CCTV workflow test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "FIR006",
            },
        )
        self.store.verify_police_complaint(
            "police_s13", case_id, "FIR006", "2024-01-05", "HQ"
        )

    def test_authorized_cctv_upload_works(self):
        self._active_case("CASE015U", "MC015U")
        submission = self.store.submit_cctv(
            "police_s13", "CASE015U", "HQ", "test.mp4", _MP4_HEADER
        )
        self.assertIsNotNone(submission)
        self.assertEqual(submission["processing_status"], "PENDING_PROCESSING")

    def test_invalid_file_extension_rejected(self):
        from services.review_store import ValidationError

        self._active_case("CASE015E", "MC015E")
        with self.assertRaises(ValidationError):
            self.store.submit_cctv(
                "police_s13", "CASE015E", "HQ", "bad_file.exe", b"garbage"
            )

    def test_cctv_analysis_requires_active_case(self):
        from services.review_store import AuthorizationError

        # Case is PENDING_POLICE_VERIFICATION — not active
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE015P",
                "child_id": "MC015P",
                "child_name": "Pending Case",
                "age": 5,
                "description": "Test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.submit_cctv(
                "police_s13", "CASE015P", "HQ", "test.mp4", _MP4_HEADER
            )

    def test_path_traversal_filename_rejected(self):
        from services.review_store import ValidationError

        self._active_case("CASE015T", "MC015T")
        with self.assertRaises(ValidationError):
            self.store.submit_cctv(
                "police_s13", "CASE015T", "HQ", "../evil.mp4", _MP4_HEADER
            )


class TestReviewerWorkflow(unittest.TestCase):
    """Reviewer can see PENDING matches and VERIFY/REJECT them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        import services.review_store as rs

        self._orig_uploads = rs.CCTV_UPLOADS_DIR
        rs.CCTV_UPLOADS_DIR = self.tmp_path / "cctv_uploads"
        rs.CCTV_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)
        self._setup_active_case_with_match()

    def tearDown(self):
        import services.review_store as rs

        rs.CCTV_UPLOADS_DIR = self._orig_uploads
        self.tmp.cleanup()

    def _setup_active_case_with_match(self):
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE016",
                "child_id": "MC016",
                "child_name": "Review Test Child",
                "age": 12,
                "description": "Reviewer workflow test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "FIR007",
            },
        )
        self.store.verify_police_complaint(
            "police_s13", "CASE016", "FIR007", "2024-01-06", "HQ"
        )
        self.match = self.store.record_potential_match(
            {
                "case_id": "CASE016",
                "child_id": "MC016",
                "track_id": 1,
                "run_id": "run016abc",
                "frame_number": 42,
                "video_name": "test.mp4",
                "face_score": 72.5,
                "overall_score": 68.0,
            }
        )

    def test_reviewer_can_see_pending_matches(self):
        matches = self.store.list_matches("reviewer_s13")
        pending = [m for m in matches if m.get("status") == "PENDING"]
        self.assertGreater(len(pending), 0)

    def test_reviewer_can_access_authorized_evidence(self):
        # Evidence access requires internal role
        evidence = self.store.get_evidence("reviewer_s13", self.match["id"])
        # May be None if no evidence file was stored — that is fine
        # The key thing is no AuthorizationError was raised
        # (evidence is None when no file was provided)

    def test_reviewer_can_verify_match(self):
        result = self.store.review_match(
            "reviewer_s13", self.match["id"], "VERIFY",
            notes="Test verification", confirmed=True
        )
        self.assertEqual(result["status"], "VERIFIED")

    def test_reviewer_can_reject_match(self):
        # Need a separate pending match for this test
        match2 = self.store.record_potential_match(
            {
                "case_id": "CASE016",
                "child_id": "MC016",
                "track_id": 2,
                "run_id": "run016def",
                "frame_number": 99,
                "video_name": "test.mp4",
                "face_score": 45.0,
                "overall_score": 40.0,
            }
        )
        result = self.store.review_match(
            "reviewer_s13", match2["id"], "REJECT", notes="Test rejection"
        )
        self.assertEqual(result["status"], "REJECTED")

    def test_terminal_review_state_cannot_be_changed(self):
        from services.review_store import ValidationError

        self.store.review_match(
            "reviewer_s13", self.match["id"], "VERIFY",
            notes="First decision", confirmed=True
        )
        with self.assertRaises(ValidationError):
            self.store.review_match(
                "reviewer_s13", self.match["id"], "REJECT", notes="Cannot change"
            )

    def test_verify_requires_confirmation(self):
        from services.review_store import ValidationError

        match3 = self.store.record_potential_match(
            {
                "case_id": "CASE016",
                "child_id": "MC016",
                "track_id": 3,
                "run_id": "run016ghi",
                "frame_number": 55,
                "video_name": "test.mp4",
            }
        )
        with self.assertRaises(ValidationError):
            self.store.review_match(
                "reviewer_s13", match3["id"], "VERIFY",
                notes="No confirmation", confirmed=False
            )


class TestAgeProgressionWorkflow(unittest.TestCase):
    """Age progression candidate lifecycle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        from cryptography.fernet import Fernet
        self.encryption_environment = patch.dict(
            os.environ, {"EVIDENCE_ENCRYPTION_KEY": Fernet.generate_key().decode()}
        )
        self.encryption_environment.start()
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)
        self._setup_case_with_references()

    def tearDown(self):
        self.encryption_environment.stop()
        self.tmp.cleanup()

    def _setup_case_with_references(self):
        from services.config import EVIDENCE_DIR
        from services.evidence_crypto import EvidenceCrypto
        from services.evidence_storage import EvidenceStorage

        evidence_dir = self.tmp_path / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE017",
                "child_id": "MC017",
                "child_name": "Age Test Child",
                "age": 5,
                "description": "Age progression test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "FIR008",
            },
        )
        self.store.verify_police_complaint(
            "police_s13", "CASE017", "FIR008", "2024-01-07", "HQ"
        )

        storage = EvidenceStorage(evidence_dir, EvidenceCrypto())
        child_opaque = storage.store_controlled("child_reference", 0, _JPEG_HEADER)
        self.child_ref = self.store.add_child_reference(
            "parent_s13", "CASE017", "child.jpeg", child_opaque
        )

        parent_opaque = storage.store_controlled("parent_reference", 0, _JPEG_HEADER)
        self.store.add_parent_reference(
            "parent_s13", "CASE017", "Parent/Guardian 1", "parent.jpeg", parent_opaque
        )

    def test_parent_reference_remains_isolated(self):
        refs = self.store.list_parent_references("parent_s13", "CASE017")
        self.assertGreater(len(refs), 0)
        for ref in refs:
            # opaque_reference is not exposed to parent through list
            self.assertNotIn("opaque_reference", ref)

    def test_candidate_begins_pending_review(self):
        candidate = self.store.create_age_progression_reference(
            "police_s13", "CASE017", self.child_ref["id"], 10,
            "TEST_PROVIDER", None
        )
        self.assertEqual(candidate["status"], "PENDING_REVIEW")

    def test_unauthorized_user_cannot_approve(self):
        from services.review_store import AuthorizationError

        candidate = self.store.create_age_progression_reference(
            "police_s13", "CASE017", self.child_ref["id"], 10,
            "TEST_PROVIDER", None
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.review_age_progression_reference(
                "parent_s13", candidate["id"], True
            )

    def test_reviewer_can_approve_candidate(self):
        candidate = self.store.create_age_progression_reference(
            "police_s13", "CASE017", self.child_ref["id"], 11,
            "TEST_PROVIDER_2", None
        )
        result = self.store.review_age_progression_reference(
            "reviewer_s13", candidate["id"], True
        )
        self.assertEqual(result["status"], "APPROVED")

    def test_reviewer_can_reject_candidate(self):
        candidate = self.store.create_age_progression_reference(
            "police_s13", "CASE017", self.child_ref["id"], 12,
            "TEST_PROVIDER_3", None
        )
        result = self.store.review_age_progression_reference(
            "reviewer_s13", candidate["id"], False
        )
        self.assertEqual(result["status"], "REJECTED")


class TestPipelineServiceValidation(unittest.TestCase):
    """Pipeline service authorization and precondition validation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        import services.review_store as rs

        self._orig_uploads = rs.CCTV_UPLOADS_DIR
        rs.CCTV_UPLOADS_DIR = self.tmp_path / "cctv_uploads"
        rs.CCTV_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)

    def tearDown(self):
        import services.review_store as rs

        rs.CCTV_UPLOADS_DIR = self._orig_uploads
        self.tmp.cleanup()

    def test_inactive_case_blocks_pipeline(self):
        from services.pipeline_service import run_cctv_analysis
        from services.review_store import AuthorizationError

        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE018",
                "child_id": "MC018",
                "child_name": "Pipeline Test",
                "age": 8,
                "description": "Pipeline service test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            run_cctv_analysis(
                "police_s13", self.store, "CASE018", "nonexistent.mp4"
            )

    def test_missing_video_raises_validation_error(self):
        from services.pipeline_service import run_cctv_analysis
        from services.review_store import AuthorizationError, ValidationError

        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASE018B",
                "child_id": "MC018B",
                "child_name": "Pipeline Test B",
                "age": 9,
                "description": "Test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "FIR009",
            },
        )
        self.store.verify_police_complaint(
            "police_s13", "CASE018B", "FIR009", "2024-01-08", "HQ"
        )
        with self.assertRaises((ValidationError, AuthorizationError)):
            run_cctv_analysis(
                "police_s13", self.store, "CASE018B", "does_not_exist.mp4"
            )

    def test_list_pending_submissions_returns_list(self):
        from services.pipeline_service import list_pending_cctv_submissions

        result = list_pending_cctv_submissions("police_s13", self.store)
        self.assertIsInstance(result, list)

    def test_embedding_profile_handoff_uses_case_data(self):
        """The UI pipeline can build the required profile without manual scripts."""
        from services.pipeline_service import _ensure_profile_exists
        from services.config import profile_path
        case = {"child_name": "Pipeline Child", "description": "blue shirt", "age": 8}
        target = profile_path("MC_S13_PROFILE")
        try:
            if target.exists():
                target.unlink()
            _ensure_profile_exists("MC_S13_PROFILE", case, "MC_S13_PROFILE.jpeg", self.store)
            self.assertTrue(target.is_file())
        finally:
            if target.exists():
                target.unlink()


class TestRoleIsolation(unittest.TestCase):
    """Regression: role separation boundaries are preserved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.store = _bootstrap(_make_store(self.tmp_path), self.tmp_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parent_cannot_view_audit_logs(self):
        from services.review_store import AuthorizationError

        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.list_audit_logs("parent_s13")

    def test_parent_cannot_create_police_case(self):
        from services.review_store import AuthorizationError

        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.create_case(
                "parent_s13",
                {
                    "case_id": "CASEISO",
                    "child_id": "MCISO",
                    "child_name": "Isolation Test",
                    "age": 5,
                    "description": "Test",
                    "reference_image": "child.jpeg",
                    "authorized_station": "HQ",
                },
            )

    def test_reviewer_cannot_verify_police_complaint(self):
        from services.review_store import AuthorizationError

        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASEISO2",
                "child_id": "MCISO2",
                "child_name": "Isolation Test 2",
                "age": 6,
                "description": "Test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        with self.assertRaises((AuthorizationError, PermissionError)):
            self.store.verify_police_complaint(
                "reviewer_s13", "CASEISO2", "FIR999", "2024-01-01", "HQ"
            )

    def test_admin_can_see_all_cases(self):
        self.store.create_preliminary_report(
            "parent_s13",
            {
                "case_id": "CASEISO3",
                "child_id": "MCISO3",
                "child_name": "Admin Visibility Test",
                "age": 7,
                "description": "Test",
                "reference_image": "child.jpeg",
                "authorized_station": "HQ",
                "police_complaint_number": "UNVERIFIED",
            },
        )
        cases = self.store.list_cases("admin_s13")
        case_ids = [c["case_id"] for c in cases]
        self.assertIn("CASEISO3", case_ids)


if __name__ == "__main__":
    unittest.main()
