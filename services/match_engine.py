"""Explainable, configurable potential-match scoring for human review."""

from __future__ import annotations

from typing import Any

try:
    from .config import MATCH_WEIGHTS
except ImportError:
    from config import MATCH_WEIGHTS


def _compare(expected: Any, observed: Any) -> float | None:
    if expected is None or observed is None:
        return None
    if isinstance(expected, str) and isinstance(observed, str):
        return 100.0 if expected.strip().lower() == observed.strip().lower() else 0.0
    if isinstance(expected, bool) and isinstance(observed, bool):
        return 100.0 if expected == observed else 0.0
    return None


def _section_evidence(section: str, expected: dict[str, Any], observed: dict[str, Any]) -> tuple[float | None, list[str], list[str], list[str]]:
    """Compare known scalar attributes and retain a human-readable audit trail."""
    scores: list[float] = []
    matched: list[str] = []
    mismatched: list[str] = []
    unknown: list[str] = []
    for key, expected_value in expected.items():
        if key == "other":  # Free text is retained for reviewers, not guessed by the prototype.
            continue
        label = f"{section}.{key}"
        observed_value = observed.get(key) if isinstance(observed, dict) else None
        comparison = _compare(expected_value, observed_value)
        if expected_value is None or observed_value is None:
            unknown.append(label)
        elif comparison == 100.0:
            scores.append(comparison)
            matched.append(label)
        elif comparison == 0.0:
            scores.append(comparison)
            mismatched.append(label)
    return (round(sum(scores) / len(scores), 2) if scores else None, matched, mismatched, unknown)


def build_match_scores(face_similarity: float, profile_attributes: dict[str, Any], observed_attributes: dict[str, Any]) -> dict[str, Any]:
    """Return score components and evidence; unknown profile data has no penalty."""
    face_score = round(max(0.0, min(1.0, face_similarity)) * 100, 2)
    clothing_score, clothing_matched, clothing_mismatched, clothing_unknown = _section_evidence("clothing", profile_attributes.get("clothing", {}), observed_attributes.get("clothing", {}))
    accessory_score, accessory_matched, accessory_mismatched, accessory_unknown = _section_evidence("accessories", profile_attributes.get("accessories", {}), observed_attributes.get("accessories", {}))
    physical_score, physical_matched, physical_mismatched, physical_unknown = _section_evidence("physical_features", profile_attributes.get("physical_features", {}), observed_attributes.get("physical_features", {}))

    weighted = [(face_score, MATCH_WEIGHTS["face"]), (clothing_score, MATCH_WEIGHTS["clothing"]), (accessory_score, MATCH_WEIGHTS["accessories"]), (physical_score, MATCH_WEIGHTS["physical_features"])]
    available = [(score, weight) for score, weight in weighted if score is not None]
    total_weight = sum(weight for _, weight in available)
    overall = round(sum(score * weight for score, weight in available) / total_weight, 2)
    return {
        "face_score": face_score, "clothing_score": clothing_score,
        "accessory_score": accessory_score, "physical_feature_score": physical_score,
        "physical_score": physical_score,  # Compatibility alias for older callers.
        "attribute_score": _mean([clothing_score, accessory_score, physical_score]),
        "overall_score": overall,
        "matched_attributes": clothing_matched + accessory_matched + physical_matched,
        "mismatched_attributes": clothing_mismatched + accessory_mismatched + physical_mismatched,
        "unknown_attributes": clothing_unknown + accessory_unknown + physical_unknown,
    }


def _mean(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return round(sum(usable) / len(usable), 2) if usable else None
