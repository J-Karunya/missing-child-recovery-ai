import unittest

from services.match_engine import build_match_scores


class MatchEngineTests(unittest.TestCase):
    def test_unknown_child_attribute_is_not_a_penalty(self):
        profile = {"clothing": {"top_color": None}, "accessories": {"glasses": None}, "physical_features": {"scar": None}}
        observed = {"clothing": {"top_color": "blue"}, "accessories": {"glasses": True}, "physical_features": {"scar": False}}
        scores = build_match_scores(0.8, profile, observed)
        self.assertEqual(scores["face_score"], 80.0)
        self.assertIsNone(scores["attribute_score"])
        self.assertEqual(scores["overall_score"], 80.0)

    def test_known_matching_attribute_adds_explainable_evidence(self):
        profile = {"clothing": {"top_color": "blue"}, "accessories": {}, "physical_features": {}}
        observed = {"clothing": {"top_color": "blue"}, "accessories": {}, "physical_features": {}}
        scores = build_match_scores(0.8, profile, observed)
        self.assertEqual(scores["clothing_score"], 100.0)
        self.assertGreater(scores["overall_score"], 80.0)

    def test_known_mismatch_is_reported_but_unknown_observation_is_not_rejected(self):
        profile = {"clothing": {}, "accessories": {"glasses": False, "cap": True}, "physical_features": {}}
        observed = {"clothing": {}, "accessories": {"glasses": True, "cap": None}, "physical_features": {}}
        scores = build_match_scores(0.8, profile, observed)
        self.assertEqual(scores["accessory_score"], 0.0)
        self.assertIn("accessories.glasses", scores["mismatched_attributes"])
        self.assertIn("accessories.cap", scores["unknown_attributes"])
