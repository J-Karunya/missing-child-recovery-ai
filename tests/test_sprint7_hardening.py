import tempfile
import unittest
from pathlib import Path
from services.backup_database import backup_database
from services.config import configuration_check
from services.mfa_service import MFAService
from services.review_store import AuthorizationError, ReviewStore, ValidationError

PASSWORD = "correct-horse-battery-staple"

class Sprint7HardeningTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.store=ReviewStore(Path(self.temp.name)/"db.sqlite"); self.store.initialize()
  self.store.create_user("admin","ADMIN","HQ",PASSWORD,"admin@test.local")
  self.store.create_user("police","POLICE","HQ",PASSWORD,"police@test.local",actor="admin")
  self.store.create_user("parent","PARENT",None,PASSWORD,"parent@test.local",actor="admin")
  self.store.create_case("police",{"case_id":"CASE1","child_id":"CHILD1","child_name":"Child","description":"desc","reference_image":"child.jpg","authorized_station":"HQ","parent_username":"parent"})
 def tearDown(self): self.temp.cleanup()
 def match(self): return self.store.record_potential_match({"case_id":"CASE1","child_id":"CHILD1","track_id":1,"run_id":"run","frame_number":1,"video_name":"x.mp4","evidence_path":"x.jpg"})
 def test_lifecycle_only_allows_audited_transitions(self):
  changed=self.store.transition_case_state("police","CASE1","UNDER_REVIEW","AI match")
  self.assertEqual(changed["lifecycle_state"],"UNDER_REVIEW")
  with self.assertRaises(ValidationError): self.store.transition_case_state("police","CASE1","ARCHIVED")
  self.assertIn("CASE_STATE_CHANGED",[x["action"] for x in self.store.list_audit_logs("admin")])
 def test_review_terminal_semantics_remain_unchanged(self):
  m=self.match(); self.store.review_match("police",m["id"],"VERIFY",confirmed=True)
  with self.assertRaises(ValidationError): self.store.review_match("police",m["id"],"REJECT",confirmed=True)
 def test_password_change_and_admin_assisted_reset(self):
  self.store.change_password("police",PASSWORD,"new-correct-horse-password")
  self.assertIsNotNone(self.store.authenticate("police","new-correct-horse-password"))
  self.store.admin_reset_password("admin","police",PASSWORD,"approved support request")
  self.assertIsNotNone(self.store.authenticate("police",PASSWORD))
  with self.assertRaises(AuthorizationError): self.store.change_password("police","wrong",PASSWORD)
 def test_mfa_boundary_never_fakes_verification(self):
  status=MFAService().enrollment_status(self.store.get_user("admin")); self.assertTrue(status["eligible"]); self.assertFalse(status["enrolled"]); self.assertFalse(MFAService().verify(self.store.get_user("admin"),"123456"))
 def test_evidence_logical_delete_is_admin_only_and_audited(self):
  m=self.match()
  with self.store._connection() as db: evidence_id=db.execute("SELECT id FROM evidence WHERE match_id=?",(m["id"],)).fetchone()[0]
  with self.assertRaises(AuthorizationError): self.store.mark_evidence_deleted("police",evidence_id,"x",True)
  self.store.mark_evidence_deleted("admin",evidence_id,"approved",True)
  with self.store._connection() as db: self.assertEqual(db.execute("SELECT evidence_status FROM evidence WHERE id=?",(evidence_id,)).fetchone()[0],"DELETED")
  self.assertIn("EVIDENCE_DELETED",[x["action"] for x in self.store.list_audit_logs("admin")])
 def test_backup_and_safe_config_check(self):
  target=backup_database(self.store.database_path,Path(self.temp.name)/"backups"); self.assertTrue(target.is_file()); self.assertGreater(target.stat().st_size,0)
  self.assertTrue(set(configuration_check().values()).issubset({"OK","MISSING"}))
 def test_audit_has_no_application_mutator_and_parent_cannot_lifecycle(self):
  self.assertFalse(hasattr(self.store,"delete_audit_log")); self.assertFalse(hasattr(self.store,"update_audit_log"))
  with self.assertRaises(AuthorizationError): self.store.transition_case_state("parent","CASE1","UNDER_REVIEW")
