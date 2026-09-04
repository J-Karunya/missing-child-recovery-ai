"""Optional real TOTP MFA; secrets are encrypted and never audited."""
from __future__ import annotations
import os
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from .review_store import AuthorizationError, ReviewStore, ValidationError
MFA_ELIGIBLE_ROLES={"ADMIN","POLICE"}
class MFAService:
 def __init__(self,store:ReviewStore|None=None,key:bytes|None=None): self.store=store; self.key=key or os.getenv("MFA_ENCRYPTION_KEY","").encode()
 def enrollment_status(self,user): return {"eligible":user.get("role") in MFA_ELIGIBLE_ROLES,"enrolled":bool(user.get("mfa_enabled")),"provider":"TOTP" if user.get("mfa_enabled") else None}
 def verify(self,user,code): return self._verify(user,code) if self.key else False
 def _f(self):
  if not self.key: raise ValidationError("MFA encryption key is not configured.")
  try:return Fernet(self.key)
  except ValueError as exc: raise ValidationError("MFA encryption key is invalid.") from exc
 def enrollment_secret(self,actor:str)->str:
  u=self.store._require(actor,"manage_cases",allow_any={"manage_users"})
  if u["role"] not in MFA_ELIGIBLE_ROLES: raise AuthorizationError("This role is not eligible for MFA enrollment.")
  secret=pyotp.random_base32()
  with self.store._connection() as db: db.execute("UPDATE users SET mfa_secret_encrypted=?,mfa_enabled=0,mfa_failed_count=0 WHERE id=?",(self._f().encrypt(secret.encode()).decode(),u["id"]))
  self.store._audit(u,"MFA_ENROLLED","user",str(u["id"]),{})
  return secret
 def _verify(self,u,code):
  try:return bool(u.get("mfa_secret_encrypted")) and pyotp.TOTP(self._f().decrypt(u["mfa_secret_encrypted"].encode()).decode()).verify(code,valid_window=0)
  except (InvalidToken,ValueError,TypeError): return False
 def enable(self,actor,code):
  u=self.store._require(actor,"manage_cases",allow_any={"manage_users"})
  if not self._verify(u,code): raise AuthorizationError("MFA verification failed.")
  with self.store._connection() as db: db.execute("UPDATE users SET mfa_enabled=1 WHERE id=?",(u["id"],))
  self.store._audit(u,"MFA_ENABLED","user",str(u["id"]),{})
 def verify_login(self,user_id,code):
  u=self.store._active_user_by_id(user_id)
  if not u.get("mfa_enabled"): return True
  ok=self._verify(u,code)
  with self.store._connection() as db: db.execute("UPDATE users SET mfa_failed_count=? WHERE id=?",(0 if ok else int(u.get("mfa_failed_count",0))+1,u["id"]))
  self.store._audit(u,"MFA_VERIFIED" if ok else "MFA_VERIFICATION_FAILED","user",str(u["id"]),{},"SUCCESS" if ok else "FAILURE")
  return ok
