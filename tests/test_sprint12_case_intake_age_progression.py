import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from services.age_progression import AgeProgressionService, DevelopmentPlaceholderProvider, ProviderUnavailable
from services.evidence_crypto import EvidenceCrypto
from services.evidence_storage import EvidenceStorage
from services.review_store import AuthorizationError, ReviewStore, ValidationError


class Sprint12CaseIntakeAgeProgressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.temp.name) / "db.sqlite")
        self.store.initialize()
        password = "correct-horse-battery-staple"
        self.store.create_user("admin", "ADMIN", "HQ", password, "admin@test.local")
        self.store.create_user("police", "POLICE", "HQ", password, "police@test.local", actor="admin")
        self.store.create_user("reviewer", "REVIEWER", "HQ", password, "reviewer@test.local", actor="admin")
        self.store.create_user("parent", "PARENT", None, password, "parent@test.local", actor="admin")
        self.store.create_user("other_parent", "PARENT", None, password, "other@test.local", actor="admin")
        self.key = Fernet.generate_key().decode()
        self.env = patch.dict(os.environ, {"EVIDENCE_ENCRYPTION_KEY": self.key})
        self.env.start()
        self.storage = EvidenceStorage(Path(self.temp.name) / "controlled", EvidenceCrypto())

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def report(self):
        return self.store.create_preliminary_report("parent", {"case_id": "REPORT1", "child_id": "CHILD1", "child_name": "Child", "age": 8, "description": "last seen", "reference_image": "child.jpg", "authorized_station": "HQ", "last_seen_location": "Park"})

    def child_reference(self):
        opaque = self.storage.store_controlled("child_reference", 0, b"\xff\xd8\xffchild")
        return self.store.add_child_reference("parent", "REPORT1", "child.jpg", opaque)

    def test_parent_report_requires_police_verification_and_blocks_ai(self):
        report = self.report()
        self.assertEqual(report["lifecycle_state"], "PENDING_POLICE_VERIFICATION")
        self.assertFalse(self.store.case_allows_ai_processing("REPORT1"))
        with self.assertRaises(AuthorizationError):
            self.store.transition_case_state("parent", "REPORT1", "ACTIVE")
        self.assertIsNone(self.store.record_pipeline_match_for_child({"child_id": "CHILD1", "track_id": 1, "run_id": "r", "frame_number": 1, "cctv_source": "clip.mp4"}))
        active = self.store.verify_police_complaint("police", "REPORT1", "FIR-1", "2026-09-03", "HQ", "checked")
        self.assertEqual(active["lifecycle_state"], "ACTIVE")
        self.assertTrue(self.store.case_allows_ai_processing("REPORT1"))
        with self.assertRaises(AuthorizationError): self.store.verify_police_complaint("reviewer", "REPORT1", "FIR-2", "2026-09-03", "HQ")
        with self.assertRaises(ValidationError): self.store.verify_police_complaint("police", "REPORT1", "FIR-2", "2026-09-03", "HQ")
        self.assertIn("POLICE_COMPLAINT_VERIFIED", [row["action"] for row in self.store.list_audit_logs("admin")])

    def test_references_are_opaque_isolated_and_progression_requires_review(self):
        self.report(); child = self.child_reference()
        parent_opaque = self.storage.store_controlled("parent_reference", 0, b"\xff\xd8\xffparent")
        parent_ref = self.store.add_parent_reference("parent", "REPORT1", "Guardian 1", "parent.jpg", parent_opaque)
        visible = self.store.list_parent_references("parent", "REPORT1")[0]
        self.assertNotIn("opaque_reference", visible)
        with self.assertRaises(AuthorizationError): self.store.list_parent_references("other_parent", "REPORT1")
        with self.assertRaises(AuthorizationError): self.store.delete_parent_reference("other_parent", parent_ref["id"], "no", True)
        unavailable = AgeProgressionService(self.store, self.storage, ProviderUnavailable())
        with self.assertRaisesRegex(ValidationError, "No age-progression provider"):
            unavailable.request("parent", "REPORT1", child["id"], 12, b"\xff\xd8\xffchild")
        service = AgeProgressionService(self.store, self.storage, DevelopmentPlaceholderProvider())
        generated = service.request("parent", "REPORT1", child["id"], 12, b"\xff\xd8\xffchild")
        self.assertEqual(generated["status"], "PENDING_REVIEW")
        self.assertIn("DEVELOPMENT_PLACEHOLDER", generated["provider"])
        with self.assertRaises(ValidationError): self.store.add_age_progression_embedding("reviewer", generated["id"], [0.1, 0.2])
        approved = self.store.review_age_progression_reference("reviewer", generated["id"], True)
        self.assertEqual(approved["status"], "APPROVED")
        embedded = self.store.add_age_progression_embedding("reviewer", generated["id"], [0.1, 0.2])
        self.assertEqual(embedded["embedding_source"], "AGE_PROGRESSED_REFERENCE")

    def test_rejection_parent_approval_and_legal_hold_are_enforced(self):
        self.report(); child = self.child_reference()
        parent_opaque = self.storage.store_controlled("parent_reference", 0, b"\xff\xd8\xffparent")
        parent_ref = self.store.add_parent_reference("parent", "REPORT1", "Guardian 1", "parent.jpg", parent_opaque)
        self.store.set_parent_reference_legal_hold("admin", parent_ref["id"], True, "active inquiry")
        with self.assertRaises(AuthorizationError): self.store.delete_parent_reference("parent", parent_ref["id"], "remove", True)
        service = AgeProgressionService(self.store, self.storage, DevelopmentPlaceholderProvider())
        generated = service.request("parent", "REPORT1", child["id"], 12, b"\xff\xd8\xffchild")
        with self.assertRaises(AuthorizationError): self.store.review_age_progression_reference("parent", generated["id"], True)
        rejected = self.store.review_age_progression_reference("reviewer", generated["id"], False)
        self.assertEqual(rejected["status"], "REJECTED")
        with self.assertRaises(ValidationError): self.store.add_age_progression_embedding("reviewer", rejected["id"], [0.1])

    def test_migration_is_idempotent_and_preserves_existing_case(self):
        self.store.create_case("police", {"case_id": "LEGACY", "child_id": "LEGACY_CHILD", "child_name": "Legacy", "age": 9, "description": "desc", "reference_image": "child.jpg", "authorized_station": "HQ"})
        self.store.initialize(); self.store.initialize()
        legacy = self.store.get_case("police", "LEGACY")
        self.assertEqual(legacy["case_status"], "ACTIVE")
        self.assertTrue(self.store.case_allows_ai_processing("LEGACY"))

    def test_reference_upload_validation_checks_content_and_paths(self):
        self.assertEqual(self.store.validate_reference_upload("photo.jpg", b"\xff\xd8\xffbytes"), "photo.jpg")
        with self.assertRaises(ValidationError): self.store.validate_reference_upload("photo.jpg", b"not-jpeg")
        with self.assertRaises(ValidationError): self.store.validate_reference_upload("../photo.jpg", b"\xff\xd8\xffbytes")
