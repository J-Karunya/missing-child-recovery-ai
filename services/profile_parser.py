"""LLM-backed conversion of a parent description into safe structured attributes.

No text-pattern or regular-expression parser is used here.  When no configured
LLM is available, the safe fallback returns unknown values rather than guessing.
"""

from __future__ import annotations

import json
import os
import warnings
from copy import deepcopy
from typing import Any, Protocol

UNKNOWN_ATTRIBUTES = {
    "clothing": {"top_color": None, "bottom_color": None, "footwear": None},
    "accessories": {
        "school_bag": None,
        "bag_color": None,
        "glasses": None,
        "cap": None,
        "mask": None,
        "watch": None,
        "other": [],
    },
    "physical_features": {"scar": None, "hair": None, "other": []},
}


class DescriptionProvider(Protocol):
    def parse(self, description: str) -> dict[str, Any]:
        """Return only the attributes object defined by UNKNOWN_ATTRIBUTES."""


def unknown_attributes() -> dict[str, Any]:
    return deepcopy(UNKNOWN_ATTRIBUTES)


def _nullable_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _nullable_text(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def normalize_attributes(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only the documented schema and coerce uncertain values to unknown."""
    result = unknown_attributes()
    if not isinstance(raw, dict):
        return result

    for section, fields in UNKNOWN_ATTRIBUTES.items():
        supplied = raw.get(section, {})
        if not isinstance(supplied, dict):
            continue
        for field, default in fields.items():
            value = supplied.get(field)
            if isinstance(default, list):
                result[section][field] = [item.strip().lower() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []
            elif isinstance(default, bool) or field in {"school_bag", "glasses", "cap", "mask", "watch", "scar"}:
                result[section][field] = _nullable_bool(value)
            else:
                result[section][field] = _nullable_text(value)
    return result


class OpenAIDescriptionProvider:
    """Optional OpenAI Structured Outputs provider, configured via environment."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("PROFILE_PARSER_MODEL", "gpt-4.1-mini")

    def parse(self, description: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the optional 'openai' package to enable LLM parsing.") from exc

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "clothing": {"type": "object", "additionalProperties": False, "properties": {"top_color": {"type": ["string", "null"]}, "bottom_color": {"type": ["string", "null"]}, "footwear": {"type": ["string", "null"]}}, "required": ["top_color", "bottom_color", "footwear"]},
                "accessories": {"type": "object", "additionalProperties": False, "properties": {"school_bag": {"type": ["boolean", "null"]}, "bag_color": {"type": ["string", "null"]}, "glasses": {"type": ["boolean", "null"]}, "cap": {"type": ["boolean", "null"]}, "mask": {"type": ["boolean", "null"]}, "watch": {"type": ["boolean", "null"]}, "other": {"type": "array", "items": {"type": "string"}}}, "required": ["school_bag", "bag_color", "glasses", "cap", "mask", "watch", "other"]},
                "physical_features": {"type": "object", "additionalProperties": False, "properties": {"scar": {"type": ["boolean", "null"]}, "hair": {"type": ["string", "null"]}, "other": {"type": "array", "items": {"type": "string"}}}, "required": ["scar", "hair", "other"]},
            },
            "required": ["clothing", "accessories", "physical_features"],
        }
        prompt = (
            "Extract only facts explicitly stated by the parent. Use true for confirmed present, "
            "false for confirmed absent, and null when unknown or uncertain. Never infer absence. "
            f"Description: {description}"
        )
        response = OpenAI(api_key=self.api_key).responses.create(
            model=self.model,
            input=prompt,
            text={"format": {"type": "json_schema", "name": "child_attributes", "strict": True, "schema": schema}},
            store=False,
        )
        return json.loads(response.output_text)


def parse_description(description: str, provider: DescriptionProvider | None = None) -> dict[str, Any]:
    """Parse a description; outages are safe because they yield unknown attributes."""
    if not isinstance(description, str) or not description.strip():
        return unknown_attributes()
    selected_provider = provider or OpenAIDescriptionProvider()
    try:
        return normalize_attributes(selected_provider.parse(description))
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        warnings.warn(f"AI profile parsing unavailable; attributes were recorded as unknown: {exc}", RuntimeWarning, stacklevel=2)
        return unknown_attributes()
