import unittest

from services.temporal_evidence import PotentialMatchRegistry, TrackEvidenceAggregator


def score(face, overall, matched=None):
    return {
        "face_score": face, "clothing_score": None, "accessory_score": None,
        "physical_feature_score": None, "overall_score": overall,
        "matched_attributes": matched or [], "mismatched_attributes": [], "unknown_attributes": [],
    }


class TemporalEvidenceTests(unittest.TestCase):
    def test_requires_multiple_frames_and_averages_scores(self):
        aggregator = TrackEvidenceAggregator(minimum_observations=3)
        self.assertFalse(aggregator.add(12, score(71, 71), 100)["ready"])
        self.assertFalse(aggregator.add(12, score(78, 78), 110)["ready"])
        result = aggregator.add(12, score(84, 84, ["clothing.top_color"]), 120)
        self.assertTrue(result["ready"])
        self.assertEqual(result["face_score"], 77.67)
        self.assertEqual(result["observation_count"], 3)
        self.assertEqual(result["best_frame_number"], 120)
        self.assertEqual(result["matched_attributes"], ["clothing.top_color"])

    def test_pending_result_is_deduplicated_per_child_and_track(self):
        registry = PotentialMatchRegistry()
        self.assertTrue(registry.mark_if_new("MC001", 12))
        self.assertFalse(registry.mark_if_new("MC001", 12))
        self.assertTrue(registry.mark_if_new("MC001", 13))
