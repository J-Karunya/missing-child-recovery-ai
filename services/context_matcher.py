"""Compatibility wrapper; new callers should use match_engine directly."""

try:
    from .match_engine import build_match_scores
except ImportError:
    from match_engine import build_match_scores


def calculate_match(face_confidence, profile_attributes, observed_attributes):
    """Return the new explainable engine's overall score without 90/10 blending."""
    scores = build_match_scores(face_confidence / 100, profile_attributes, observed_attributes)
    return scores["overall_score"]
