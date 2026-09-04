import tempfile,unittest
from pathlib import Path
from cryptography.fernet import Fernet
import pyotp
from services.evidence_crypto import EvidenceCrypto
from services.mfa_service import MFAService
from services.review_store import AuthorizationError,ReviewStore,ValidationError
from services.session_service import SessionService
from services.upload_scanner import UploadScanService
P="correct-horse-battery-staple"
class Sprint8SecurityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=ReviewStore(Path(self.tmp.name)/"x.db");self.s.initialize();self.s.create_user("admin","ADMIN","HQ",P,"a@x.test");self.s.create_user("police","POLICE","HQ",P,"p@x.test",actor="admin");self.s.create_user("parent","PARENT",None,P,"r@x.test",actor="admin")
  self.s.create_case("police",{"case_id":"C1","child_id":"K1","child_name":"K","description":"d","reference_image":"k.jpg","authorized_station":"HQ","parent_username":"parent"})
 def tearDown(self):self.tmp.cleanup()
 def match(self):return self.s.record_potential_match({"case_id":"C1","child_id":"K1","track_id":1,"run_id":"r","frame_number":1,"video_name":"v.mp4","evidence_path":"a.jpg"})
 def test_totp_required_cannot_bypass_and_secrets_not_audited(self):
  key=Fernet.generate_key();m=MFAService(self.s,key);secret=m.enrollment_secret("admin");m.enable("admin",pyotp.TOTP(secret).now());self.assertFalse(m.verify_login(self.s.get_user("admin")["id"],"000000"));self.assertTrue(m.verify_login(self.s.get_user("admin")["id"],pyotp.TOTP(secret).now()));self.assertNotIn(secret," ".join(x["details"] or "" for x in self.s.list_audit_logs("admin")))
 def test_server_sessions_are_random_revocable_and_recheck_user(self):
  ss=SessionService(self.s,30);a,b=ss.create(self.s.get_user("police")["id"]),ss.create(self.s.get_user("police")["id"]);self.assertNotEqual(a,b);self.assertEqual(ss.validate(a)["username"],"police");ss.revoke(a)
  with self.assertRaises(AuthorizationError):ss.validate(a)
  self.s.deactivate_user("admin","police",False)
  with self.assertRaises(AuthorizationError):ss.validate(b)
 def test_evidence_crypto_authenticates_and_parents_cannot_decrypt(self):
  c=EvidenceCrypto(Fernet.generate_key());blob=c.encrypt(b"evidence");self.assertEqual(c.decrypt(blob),b"evidence")
  with self.assertRaises(ValidationError):c.decrypt(blob[:-1]+b"x")
  m=self.match()
  with self.assertRaises(AuthorizationError):c.decrypt_for(self.s,"parent",m["id"],blob)
 def test_scanner_is_fail_closed(self):
  self.assertFalse(UploadScanService().processable(b"x","x.mp4"))
  class Clean: 
   def scan(self,c,f):return "CLEAN"
  self.assertTrue(UploadScanService(Clean()).processable(b"x","x.mp4"))
 def test_legal_hold_blocks_logical_deletion(self):
  m=self.match()
  with self.s._connection() as db:eid=db.execute("SELECT id FROM evidence WHERE match_id=?",(m["id"],)).fetchone()[0]
  self.s.set_evidence_legal_hold("admin",eid,True,"investigation")
  with self.assertRaises(AuthorizationError):self.s.mark_evidence_deleted("admin",eid,"no",True)
  with self.assertRaises(AuthorizationError):self.s.set_evidence_legal_hold("parent",eid,False,"no")
