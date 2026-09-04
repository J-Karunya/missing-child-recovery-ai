"""Fernet evidence encryption boundary; authorization is checked before decryption."""
from __future__ import annotations
import os
from cryptography.fernet import Fernet,InvalidToken
from .review_store import AuthorizationError,ValidationError
class EvidenceCrypto:
 def __init__(self,key:bytes|None=None):self.key=key or os.getenv("EVIDENCE_ENCRYPTION_KEY","").encode()
 def _f(self):
  if not self.key:raise ValidationError("Evidence encryption key is not configured.")
  try:return Fernet(self.key)
  except ValueError as exc:raise ValidationError("Evidence encryption key is invalid.") from exc
 def encrypt(self,data:bytes)->bytes:return self._f().encrypt(data)
 def decrypt(self,data:bytes)->bytes:
  try:return self._f().decrypt(data)
  except InvalidToken as exc:raise ValidationError("Encrypted evidence is corrupted or cannot be authenticated.") from exc
 def decrypt_for(self,store,actor,match_id,data):
  if actor and store.get_user(actor).get("role")=="PARENT":raise AuthorizationError("Parents cannot decrypt evidence.")
  store.get_evidence(actor,match_id); return self.decrypt(data)
