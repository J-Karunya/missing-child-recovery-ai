"""Build a consistent parsed profile from a raw child profile."""

from __future__ import annotations

import json

try:
    from .config import ACTIVE_CHILD_ID, PARSED_PROFILES_DIR, ensure_runtime_directories, profile_path, safe_filename
    from .profile_parser import DescriptionProvider, parse_description
except ImportError:  # Supports `python services/profile_builder.py`.
    from config import ACTIVE_CHILD_ID, PARSED_PROFILES_DIR, ensure_runtime_directories, profile_path, safe_filename
    from profile_parser import DescriptionProvider, parse_description


class ProfileBuilder:
    def __init__(self, provider: DescriptionProvider | None = None) -> None:
        self.provider = provider

    def build_profile(self, profile: dict) -> dict:
        return validate_child_profile(profile, self.provider)


def validate_child_profile(profile: dict, provider: DescriptionProvider | None = None) -> dict:
    """Validate raw case data before it enters the matching pipeline.

    Age is useful case context but remains optional. The attributes object is
    always produced by the optional semantic parser, never by regex guesses.
    """
    if not isinstance(profile, dict):
        raise ValueError("Child profile must be a JSON object.")
    required = {"child_id", "name", "description"}
    missing = required - profile.keys()
    if missing:
        raise ValueError(f"Child profile is missing required fields: {', '.join(sorted(missing))}")
    if not isinstance(profile["child_id"], str) or not profile["child_id"].strip():
        raise ValueError("Child profile field 'child_id' must be a non-empty string.")
    try:
        safe_filename(profile["child_id"])
    except ValueError as exc:
        raise ValueError("Child profile field 'child_id' must be a simple identifier, not a path.") from exc
    if not isinstance(profile["name"], str) or not profile["name"].strip():
        raise ValueError("Child profile field 'name' must be a non-empty string.")
    if not isinstance(profile["description"], str):
        raise ValueError("Child profile field 'description' must be a string.")
    if "age" in profile and profile["age"] is not None and (not isinstance(profile["age"], int) or isinstance(profile["age"], bool) or profile["age"] < 0):
        raise ValueError("Child profile field 'age' must be a non-negative whole number when provided.")
    return {
        "child_id": profile["child_id"],
        "name": profile["name"],
        "age": profile.get("age"),
        "description": profile["description"],
        "attributes": parse_description(profile["description"], provider),
    }


def main() -> None:
    ensure_runtime_directories()
    source_path = profile_path(ACTIVE_CHILD_ID)
    if not source_path.is_file():
        raise FileNotFoundError(f"Child profile not found: {source_path}")
    try:
        profile = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Child profile is unreadable: {source_path}. Correct the JSON and try again.") from exc
    parsed = ProfileBuilder().build_profile(profile)
    save_path = PARSED_PROFILES_DIR / f"{parsed['child_id']}.json"
    save_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    print(f"Parsed profile saved: {save_path}")
    print("Note: without a configured LLM, attributes are safely recorded as unknown.")


if __name__ == "__main__":
    main()
