import unittest

from services.profile_builder import ProfileBuilder, validate_child_profile
from services.profile_parser import parse_description


class StubProvider:
    def __init__(self, attributes):
        self.attributes = attributes

    def parse(self, description):
        return self.attributes


def attributes(**accessories):
    return {
        "clothing": {"top_color": None, "bottom_color": None, "footwear": None},
        "accessories": {"school_bag": None, "bag_color": None, "glasses": None, "cap": None, "mask": None, "watch": None, "other": [], **accessories},
        "physical_features": {"scar": None, "hair": None, "other": []},
    }


class ProfileParserTests(unittest.TestCase):
    def test_negative_description_is_false_when_llm_confirms_it(self):
        result = parse_description("No glasses.", StubProvider(attributes(glasses=False)))
        self.assertIs(result["accessories"]["glasses"], False)

    def test_unsure_description_is_unknown_when_llm_confirms_it(self):
        result = parse_description("Parents are unsure about glasses.", StubProvider(attributes(glasses=None)))
        self.assertIsNone(result["accessories"]["glasses"])

    def test_present_description_is_true_when_llm_confirms_it(self):
        result = parse_description("Child is wearing glasses.", StubProvider(attributes(glasses=True)))
        self.assertIs(result["accessories"]["glasses"], True)

    def test_unavailable_provider_fails_safe_to_unknown(self):
        result = parse_description("No glasses.", StubProvider(None))
        self.assertIsNone(result["accessories"]["glasses"])

    def test_builder_returns_consistent_schema(self):
        profile = {"child_id": "MC001", "name": "Example", "age": 10, "description": "No glasses."}
        result = ProfileBuilder(StubProvider(attributes(glasses=False))).build_profile(profile)
        self.assertEqual(result["child_id"], "MC001")
        self.assertIn("attributes", result)
        self.assertIs(result["attributes"]["accessories"]["glasses"], False)

    def test_partial_description_keeps_unmentioned_fields_unknown(self):
        result = parse_description(
            "Blue shirt and black backpack.",
            StubProvider({
                "clothing": {"top_color": "blue", "bottom_color": None, "footwear": None},
                "accessories": {"school_bag": True, "bag_color": "black", "glasses": None, "cap": None, "mask": None, "watch": None, "other": []},
                "physical_features": {"scar": None, "hair": None, "other": []},
            }),
        )
        self.assertEqual(result["clothing"]["top_color"], "blue")
        self.assertIsNone(result["accessories"]["glasses"])

    def test_profile_requires_identity_name_and_description(self):
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            validate_child_profile({"child_id": "MC001", "name": "Example"})

    def test_age_is_optional_but_invalid_age_is_rejected(self):
        valid = validate_child_profile({"child_id": "MC001", "name": "Example", "description": ""}, StubProvider(attributes()))
        self.assertIsNone(valid["age"])
        with self.assertRaisesRegex(ValueError, "age"):
            validate_child_profile({"child_id": "MC001", "name": "Example", "description": "", "age": -1})
