"""Validation and event logging helpers."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    from .config import LOGS_DIR, ensure_runtime_directories
except ImportError:
    from config import LOGS_DIR, ensure_runtime_directories

EVENT_FIELDS = ["timestamp", "run_id", "child_id", "track_id", "frame_number", "face_score", "clothing_score", "accessory_score", "physical_feature_score", "attribute_score", "overall_score", "matched_attributes", "mismatched_attributes", "unknown_attributes", "evidence_reasons", "observation_count", "verification_status", "status", "evidence_image", "evidence_metadata", "cctv_source", "lighting_condition"]
AUDIT_FIELDS = ["timestamp", "run_id", "action", "child_id", "cctv_source", "outcome"]


def load_embedding_file(path: Path) -> np.ndarray:
    """Load a non-empty, finite, one-dimensional embedding with useful errors."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Embedding file is missing or empty: {path}. Run generate_embedding.py again.")
    try:
        embedding = np.load(path, allow_pickle=False)
    except (OSError, ValueError, EOFError) as exc:
        raise ValueError(f"Embedding file is corrupted: {path}. Run generate_embedding.py again.") from exc
    if embedding.ndim != 1 or embedding.size == 0 or not np.isfinite(embedding).all():
        raise ValueError(f"Embedding file is invalid: {path}. Run generate_embedding.py again.")
    embedding = embedding.astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError(f"Embedding file has no usable vector: {path}. Run generate_embedding.py again.")
    # Generated embeddings are normalized. Normalizing a valid legacy vector
    # here preserves cosine-similarity semantics without altering source data.
    return embedding / norm


def log_potential_match(event: dict[str, object]) -> Path:
    """Append a pending-review event at a stable project-relative location."""
    ensure_runtime_directories()
    csv_path = LOGS_DIR / "match_events.csv"
    new_file = not csv_path.exists()
    row = {field: event.get(field, "") for field in EVENT_FIELDS}
    for field in ("matched_attributes", "mismatched_attributes", "unknown_attributes"):
        if isinstance(row[field], list):
            row[field] = "; ".join(row[field])
    if isinstance(row["evidence_reasons"], (dict, list)):
        row["evidence_reasons"] = json.dumps(row["evidence_reasons"], sort_keys=True)
    row["timestamp"] = row["timestamp"] or datetime.now(timezone.utc).isoformat()
    row["verification_status"] = row["verification_status"] or row["status"] or "PENDING"
    row["status"] = row["status"] or row["verification_status"]
    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EVENT_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return csv_path


def log_audit_event(event: dict[str, object]) -> Path:
    """Append minimal, non-biometric run lifecycle information for review."""
    ensure_runtime_directories()
    audit_path = LOGS_DIR / "audit_events.csv"
    new_file = not audit_path.exists()
    row = {field: event.get(field, "") for field in AUDIT_FIELDS}
    row["timestamp"] = row["timestamp"] or datetime.now(timezone.utc).isoformat()
    with audit_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=AUDIT_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return audit_path
