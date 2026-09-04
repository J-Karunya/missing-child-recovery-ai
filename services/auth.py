"""Argon2 authentication and short-lived Streamlit-session helpers.

Passwords are accepted only at login/user-creation boundaries. This module never
returns, logs, or stores plaintext passwords; SQLite stores Argon2 hashes only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

try:
    from .config import SESSION_TIMEOUT_MINUTES
except ImportError:
    from config import SESSION_TIMEOUT_MINUTES


_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    return _HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash or not isinstance(password, str):
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str | None) -> bool:
    return bool(password_hash and _HASHER.check_needs_rehash(password_hash))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def build_session(user: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret session state suitable for Streamlit session_state."""
    timestamp = iso_now()
    return {"user_id": user["id"], "username": user["username"], "role": user["role"], "issued_at": timestamp, "last_seen_at": timestamp}


def session_expired(session: dict[str, Any], timeout_minutes: int = SESSION_TIMEOUT_MINUTES) -> bool:
    try:
        last_seen = datetime.fromisoformat(str(session["last_seen_at"]))
    except (KeyError, TypeError, ValueError):
        return True
    return now_utc() - last_seen > timedelta(minutes=timeout_minutes)


def refresh_session(session: dict[str, Any]) -> dict[str, Any]:
    updated = dict(session)
    updated["last_seen_at"] = iso_now()
    return updated
