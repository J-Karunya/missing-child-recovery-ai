"""Small, deterministic multi-frame evidence aggregation for one DeepSORT track."""

from __future__ import annotations

from typing import Any


class TrackEvidenceAggregator:
    """Keep the best observed evidence and average scores across a short track."""

    def __init__(self, minimum_observations: int = 3) -> None:
        self.minimum_observations = max(1, minimum_observations)
        self._observations: dict[int, list[dict[str, Any]]] = {}

    def add(self, track_id: int, scores: dict[str, Any], frame_number: int) -> dict[str, Any]:
        observation = {**scores, "frame_number": frame_number}
        entries = self._observations.setdefault(track_id, [])
        entries.append(observation)
        numeric_keys = ("face_score", "clothing_score", "accessory_score", "physical_feature_score", "overall_score")
        aggregate = {key: self._average(entries, key) for key in numeric_keys}
        best = max(entries, key=lambda item: item["overall_score"])
        aggregate.update({
            "track_id": track_id,
            "observation_count": len(entries),
            "best_frame_number": best["frame_number"],
            "matched_attributes": self._unique(entries, "matched_attributes"),
            "mismatched_attributes": self._unique(entries, "mismatched_attributes"),
            "unknown_attributes": self._unique(entries, "unknown_attributes"),
            "ready": len(entries) >= self.minimum_observations,
        })
        return aggregate

    @staticmethod
    def _average(entries: list[dict[str, Any]], key: str) -> float | None:
        values = [entry[key] for entry in entries if isinstance(entry.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    @staticmethod
    def _unique(entries: list[dict[str, Any]], key: str) -> list[str]:
        return list(dict.fromkeys(value for entry in entries for value in entry.get(key, [])))


class PotentialMatchRegistry:
    """Deduplicate one child/track pair within a single matcher run."""

    def __init__(self) -> None:
        self._emitted: set[tuple[str, int]] = set()

    def mark_if_new(self, child_id: str, track_id: int) -> bool:
        key = (child_id, track_id)
        if key in self._emitted:
            return False
        self._emitted.add(key)
        return True
