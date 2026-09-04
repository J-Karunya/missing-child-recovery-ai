"""Parent-assisted age-progression boundary.

This module does not infer genetics.  A configured provider may offer an
AI-assisted appearance estimate; its result is always PENDING_REVIEW and only
an authorized reviewer can approve it for a separate InsightFace embedding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .evidence_crypto import EvidenceCrypto
from .evidence_storage import EvidenceStorage
from .review_store import ReviewStore, ValidationError


class AgeProgressionProvider(Protocol):
    name: str
    def generate(self, child_image: bytes, child_current_age: int, target_age: int,
                 parent_images: list[bytes]) -> bytes: ...


class ProviderUnavailable:
    name = "UNAVAILABLE"
    def generate(self, child_image: bytes, child_current_age: int, target_age: int, parent_images: list[bytes]) -> bytes:
        raise ValidationError("No age-progression provider is configured; no reference image was generated.")


class DevelopmentPlaceholderProvider:
    """Explicit test-only fallback. It returns no claimed age transformation."""
    name = "DEVELOPMENT_PLACEHOLDER_NO_GENETIC_PREDICTION"
    def generate(self, child_image: bytes, child_current_age: int, target_age: int, parent_images: list[bytes]) -> bytes:
        if not child_image:
            raise ValidationError("A controlled child reference image is required.")
        # It deliberately does not combine parent features or claim a prediction.
        return child_image


@dataclass
class AgeProgressionService:
    store: ReviewStore
    storage: EvidenceStorage
    provider: AgeProgressionProvider

    @classmethod
    def unavailable(cls, store: ReviewStore, root) -> "AgeProgressionService":
        return cls(store, EvidenceStorage(root, EvidenceCrypto()), ProviderUnavailable())

    def request(self, actor: str, case_id: str, child_reference_id: int, target_age: int,
                child_image: bytes, parent_images: list[bytes] | None = None) -> dict:
        case = self.store._case_for(case_id)
        if not case:
            raise ValidationError("Case does not exist.")
        generated = self.provider.generate(child_image, int(case.get("age") or 0), target_age, parent_images or [])
        reference = self.store.create_age_progression_reference(actor, case_id, child_reference_id, target_age, self.provider.name, None)
        opaque = self.storage.store_controlled("age_progression", int(reference["id"]), generated)
        self.store.attach_age_progression_output(int(reference["id"]), opaque)
        return self.store._row_for_progression(int(reference["id"]))
