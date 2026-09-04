"""SQLite-backed prototype server-side sessions; raw tokens are never stored."""
from __future__ import annotations
import hashlib,secrets
from datetime import datetime,timedelta,timezone
from .review_store import AuthorizationError,ReviewStore,_now,_row
class SessionService:
 def __init__(self,store,minutes=30):self.store,self.minutes=store,minutes
 def create(self,user_id):
  u=self.store._active_user_by_id(user_id); token=secrets.token_urlsafe(32); now=datetime.now(timezone.utc); exp=now+timedelta(minutes=self.minutes)
  with self.store._connection() as db:db.execute("INSERT INTO server_sessions(token_hash,user_id,created_at,expires_at,last_activity_at) VALUES(?,?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),u["id"],now.isoformat(),exp.isoformat(),now.isoformat()))
  return token
 def validate(self,token):
  with self.store._connection() as db:r=_row(db.execute("SELECT * FROM server_sessions WHERE token_hash=?",(hashlib.sha256(str(token).encode()).hexdigest(),)).fetchone())
  if not r or r["revoked_at"] or datetime.fromisoformat(r["expires_at"])<=datetime.now(timezone.utc):raise AuthorizationError("Session is expired or unavailable.")
  return self.store._active_user_by_id(r["user_id"])
 def revoke(self,token):
  with self.store._connection() as db:db.execute("UPDATE server_sessions SET revoked_at=? WHERE token_hash=?",(_now(),hashlib.sha256(str(token).encode()).hexdigest()))
