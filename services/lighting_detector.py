"""Lightweight lighting label for future CCTV enhancement, not a new model."""

from __future__ import annotations

import numpy as np


def classify_lighting(frame: np.ndarray) -> str:
    """Return DAY or NIGHT from brightness while accepting colour or grayscale frames.

    The result is descriptive metadata only. No brightness enhancement or
    rejection occurs, so low-light and grayscale footage remain processable.
    """
    if frame is None or frame.size == 0:
        return "UNKNOWN"
    luminance = frame if frame.ndim == 2 else np.mean(frame, axis=2)
    return "NIGHT" if float(np.mean(luminance)) < 60 else "DAY"
