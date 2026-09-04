"""Conservative visual attributes for the current colour-CCTV pipeline.

Only coarse clothing colour is implemented with the project's current
dependencies. Every unsupported or unreliable field remains ``None``: this is
important because an unknown CCTV observation must not become invented evidence.
"""

from __future__ import annotations

import numpy as np

try:
    from .profile_parser import unknown_attributes
except ImportError:
    from profile_parser import unknown_attributes


def dominant_color(region: np.ndarray) -> np.ndarray | None:
    if region.size == 0:
        return None
    return np.mean(region.reshape(-1, 3), axis=0)


def classify_bgr(color: np.ndarray | None) -> str | None:
    """A small placeholder until the later visual-attribute model sprint."""
    if color is None:
        return None
    blue, green, red = color
    if max(blue, green, red) < 80:
        return "black"
    if min(blue, green, red) > 180:
        return "white"
    if blue > red and blue > green:
        return "blue"
    if red > blue and red > green:
        return "red"
    return None


def extract_attributes(person_crop: np.ndarray) -> dict:
    """Return only attributes actually observable by this basic extractor."""
    result = unknown_attributes()
    if person_crop is None or person_crop.ndim != 3 or person_crop.size == 0:
        return result
    height = person_crop.shape[0]
    top_region = person_crop[int(height * 0.2):int(height * 0.5), :]
    result["clothing"]["top_color"] = classify_bgr(dominant_color(top_region))
    return result
