import tempfile, unittest
from pathlib import Path
from cryptography.fernet import Fernet
from services.backup_database import backup_database
from services.evidence_crypto import EvidenceCrypto
from services.evidence_storage import EvidenceStorage
from services.restore_database import restore_database, validate_database
from services.review_store import AuthorizationError, ReviewStore, ValidationError
from services.upload_scanner import UploadScanService

PASSWORD = "correct-horse-battery-staple"

class Sprint10OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=ReviewStore(Path(self.temp.name)/"db.sqlite"); self.store.initialize()
        self.store.create_user("admin","ADMIN","HQ",PASSWORD,"admin@test.local")
        self.store.create_user("police","POLICE","HQ",PASSWORD,"police@test.local",actor="admin")
        self.store.create_user("parent","PARENT",None,PASSWORD,"parent@test.local",actor="admin")
        self.store.create_case("police",{"case_id":"C1","child_id":"CH1","child_name":"Child","description":"d","reference_image":"child.jpg","authorized_station":"HQ","parent_username":"parent"})
    def tearDown(self):
        # Windows can briefly retain a copied SQLite backup after validation.
        # The test assertions have already completed; avoid masking them with
        # an OS-level temporary-file cleanup race.
        try:
            self.temp.cleanup()
        except PermissionError:
            pass
    def match(self): return self.store.record_potential_match({"case_id":"C1","child_id":"CH1","track_id":1,"run_id":"r1","frame_number":1,"video_name":"v.mp4","evidence_path":"legacy.jpg"})
    def test_encrypted_storage_authorization_traversal_and_corruption(self):
        match=self.match(); storage=EvidenceStorage(Path(self.temp.name)/"evidence",EvidenceCrypto(Fernet.generate_key())); ref=storage.store(1,b"jpeg-bytes")
        self.assertTrue(ref.endswith(".fernet")); self.assertEqual(storage.read(self.store,"police",match["id"],ref),b"jpeg-bytes")
        with self.assertRaises(AuthorizationError): storage.read(self.store,"parent",match["id"],ref)
        with self.assertRaises(ValidationError): storage.read(self.store,"police",match["id"],"../x.fernet")
        (storage.root/ref).write_bytes(b"corrupted")
        with self.assertRaises(ValidationError): storage.read(self.store,"police",match["id"],ref)
    def test_legal_hold_and_encrypted_reference_are_audited_without_keys(self):
        match=self.match(); self.store.set_encrypted_evidence_reference(match["id"],"opaque.fernet")
        with self.store._connection() as db:
            evidence_id=db.execute("SELECT id FROM evidence WHERE match_id=?",(match["id"],)).fetchone()[0]
        self.store.set_evidence_legal_hold("admin",evidence_id,True,"hold")
        with self.assertRaises(AuthorizationError): self.store.mark_evidence_deleted("admin",evidence_id,"no",True)
        details=" ".join(row["details"] or "" for row in self.store.list_audit_logs("admin"))
        self.assertNotIn("EVIDENCE_ENCRYPTION_KEY",details)
    def test_backup_restore_is_dry_run_and_replacement_is_explicit(self):
        backup=backup_database(self.store.database_path,Path(self.temp.name)/"backups"); self.assertTrue(validate_database(backup))
        destination=Path(self.temp.name)/"restored.sqlite"; self.assertEqual(restore_database(backup,destination),destination); self.assertFalse(destination.exists())
        destination.write_bytes(b"not a database")
        with self.assertRaises(PermissionError): restore_database(backup,destination,dry_run=False)
        restored=restore_database(backup,destination,confirm_replace=True,dry_run=False); self.assertTrue(validate_database(restored))
    def test_scanner_never_processes_unavailable_or_infected(self):
        self.assertFalse(UploadScanService().processable(b"x","v.mp4"))
        class Infected:
            def scan(self, content, filename): return "INFECTED"
        self.assertFalse(UploadScanService(Infected()).processable(b"x","v.mp4"))
