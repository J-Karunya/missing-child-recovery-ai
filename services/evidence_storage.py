"""Controlled encrypted evidence storage using the existing Fernet boundary."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .evidence_crypto import EvidenceCrypto
from .review_store import AuthorizationError, ValidationError


class EvidenceStorage:
    def __init__(self, root: Path, crypto: EvidenceCrypto) -> None:
        self.root = Path(root)
        self.crypto = crypto
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, evidence_id: int, content: bytes) -> str:
        if not isinstance(evidence_id, int) or evidence_id < 1 or not content:
            raise ValidationError("Evidence ID and content are required.")
        return self.store_controlled("evidence", evidence_id, content)

    def store_controlled(self, category: str, record_id: int, content: bytes) -> str:
        """Persist a sensitive image under an opaque, encrypted reference."""
        if category not in {"evidence", "child_reference", "parent_reference", "age_progression"}:
            raise ValidationError("Unsupported controlled storage category.")
        if not isinstance(record_id, int) or record_id < 0 or not content:
            raise ValidationError("Controlled record ID and content are required.")
        reference = f"{category}_{record_id}_{uuid4().hex}.fernet"
        (self.root / reference).write_bytes(self.crypto.encrypt(content))
        return reference

    def read_controlled(self, reference: str) -> bytes:
        if Path(reference).name != reference or not reference.endswith(".fernet"):
            raise ValidationError("Invalid controlled evidence reference.")
        path = self.root / reference
        if not path.is_file():
            raise ValidationError("Controlled evidence is unavailable.")
        return self.crypto.decrypt(path.read_bytes())

    def read(self, store, actor: str, match_id: int, reference: str) -> bytes:
        if Path(reference).name != reference or not reference.endswith(".fernet"):
            raise ValidationError("Invalid controlled evidence reference.")
        if store.get_user(actor).get("role") == "PARENT":
            raise AuthorizationError("Parents cannot access encrypted evidence.")
        path = self.root / reference
        if not path.is_file():
            raise ValidationError("Controlled evidence is unavailable.")
        store.get_evidence(actor, match_id)
        return self.crypto.decrypt(path.read_bytes())
