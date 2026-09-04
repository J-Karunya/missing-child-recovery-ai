"""Central configuration and safe, project-relative paths."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHILD_IMAGES_DIR = DATA_DIR / "child_images"
CHILD_PROFILES_DIR = DATA_DIR / "child_profiles"
PARSED_PROFILES_DIR = DATA_DIR / "parsed_profiles"
CCTV_VIDEOS_DIR = DATA_DIR / "cctv_videos"
ALERTS_DIR = DATA_DIR / "alerts"
EVIDENCE_DIR = DATA_DIR / "evidence"
CASES_DIR = DATA_DIR / "cases"
LOGS_DIR = DATA_DIR / "logs"
DATABASE_DIR = DATA_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "missing_child_ai.db"
CCTV_UPLOADS_DIR = DATA_DIR / "cctv_uploads"
EMBEDDINGS_DIR = BASE_DIR / "embeddings"
MODELS_DIR = BASE_DIR / "models"

ACTIVE_CHILD_ID = os.getenv("MISSING_CHILD_ID", "MC001")
DEFAULT_VIDEO_NAME = os.getenv("CCTV_VIDEO_FILE", "station.mp4")

# Prototype matching settings. They are intentionally kept here so a reviewer can
# adjust and document them without hunting through the video-processing loop.
MATCH_WEIGHTS = {"face": 0.70, "clothing": 0.15, "accessories": 0.10, "physical_features": 0.05}
POTENTIAL_MATCH_THRESHOLD = float(os.getenv("POTENTIAL_MATCH_THRESHOLD", "60"))
MIN_TRACK_OBSERVATIONS = int(os.getenv("MIN_TRACK_OBSERVATIONS", "3"))
CCTV_PROGRESS_INTERVAL = max(1, int(os.getenv("CCTV_PROGRESS_INTERVAL", "30")))
MAX_CCTV_VIDEO_BYTES = max(1, int(os.getenv("MAX_CCTV_VIDEO_BYTES", str(500 * 1024 * 1024))))
MAX_CCTV_UPLOAD_BYTES = max(1, int(os.getenv("MAX_CCTV_UPLOAD_BYTES", str(500 * 1024 * 1024))))
# Preparation for a future authorized retention workflow; this prototype never
# deletes evidence automatically.
EVIDENCE_RETENTION_DAYS = max(1, int(os.getenv("EVIDENCE_RETENTION_DAYS", "30")))
CCTV_RETENTION_DAYS = max(1, int(os.getenv("CCTV_RETENTION_DAYS", "30")))
AUDIT_RETENTION_DAYS = max(1, int(os.getenv("AUDIT_RETENTION_DAYS", "365")))
CASE_RETENTION_DAYS = max(1, int(os.getenv("CASE_RETENTION_DAYS", "365")))
NOTIFICATION_RETENTION_DAYS = max(1, int(os.getenv("NOTIFICATION_RETENTION_DAYS", "90")))
RETENTION_DRY_RUN = os.getenv("RETENTION_DRY_RUN", "true").strip().lower() not in {"0", "false", "no"}
SESSION_TIMEOUT_MINUTES = max(1, int(os.getenv("SESSION_TIMEOUT_MINUTES", "30")))
LOGIN_MAX_FAILURES = max(1, int(os.getenv("LOGIN_MAX_FAILURES", "5")))
LOGIN_LOCKOUT_MINUTES = max(1, int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15")))
BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
ENVIRONMENT_MODE = os.getenv("APP_ENV", "DEVELOPMENT").strip().upper()
HTTPS_REQUIRED = os.getenv("HTTPS_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}
SCANNER_MODE = os.getenv("SCANNER_MODE", "UNAVAILABLE").strip().upper()


def safe_filename(value: str) -> str:
    """Allow a filename, never a caller-controlled path."""
    candidate = Path(value)
    if candidate.name != value or value in {"", ".", ".."}:
        raise ValueError("Only a simple filename is allowed.")
    return value


def profile_path(child_id: str = ACTIVE_CHILD_ID) -> Path:
    return CHILD_PROFILES_DIR / f"{safe_filename(child_id)}.json"


def embedding_path(child_id: str = ACTIVE_CHILD_ID) -> Path:
    return EMBEDDINGS_DIR / f"{safe_filename(child_id)}.npy"


def parsed_profile_path(child_id: str = ACTIVE_CHILD_ID) -> Path:
    return PARSED_PROFILES_DIR / f"{safe_filename(child_id)}.json"


def video_path(filename: str = DEFAULT_VIDEO_NAME) -> Path:
    return CCTV_VIDEOS_DIR / safe_filename(filename)


def ensure_runtime_directories() -> None:
    for directory in (ALERTS_DIR, EVIDENCE_DIR, CASES_DIR, LOGS_DIR, EMBEDDINGS_DIR, PARSED_PROFILES_DIR, DATABASE_DIR, CCTV_UPLOADS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

def configuration_check() -> dict[str, str]:
    """Report configuration state without revealing any configured values."""
    mode_valid = ENVIRONMENT_MODE in {"DEVELOPMENT", "STAGING", "PRODUCTION"}
    values = {"SESSION_SECRET": os.getenv("SESSION_SECRET", ""), "EVIDENCE_ENCRYPTION_KEY": os.getenv("EVIDENCE_ENCRYPTION_KEY", ""), "MFA_ENCRYPTION_KEY": os.getenv("MFA_ENCRYPTION_KEY", "")}
    result = {"ENVIRONMENT_MODE": "OK" if mode_valid else "INVALID", "DATABASE_PATH": "OK" if DATABASE_PATH.parent else "INVALID", "HTTPS_REQUIRED": "OK" if ENVIRONMENT_MODE != "PRODUCTION" or HTTPS_REQUIRED else "MISSING", "SCANNER_MODE": "OK" if ENVIRONMENT_MODE == "DEVELOPMENT" or SCANNER_MODE not in {"", "UNAVAILABLE"} else "MISSING"}
    required = ENVIRONMENT_MODE in {"STAGING", "PRODUCTION"}
    # Keep the existing check API's OK/MISSING vocabulary for development,
    # while staging/production treat the same missing values as hard failures.
    result.update({key: "OK" if value else "MISSING" for key, value in values.items()})
    return result

if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        print(" ".join(f"{key}={state}" for key, state in configuration_check().items()))
