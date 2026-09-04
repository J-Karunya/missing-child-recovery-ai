"""YOLO detector loading with safe recovery for the official small model."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from .config import MODELS_DIR
except ImportError:  # Supports `python services/detector.py`.
    from config import MODELS_DIR

MODEL_FILENAME = "yolov8n.pt"
MIN_VALID_MODEL_BYTES = 1_000_000


def model_path() -> Path:
    """Return the controlled, project-relative location of the YOLO weights."""
    return MODELS_DIR / MODEL_FILENAME


def model_file_status(path: Path | None = None) -> str | None:
    """Return a clear reason a local model cannot safely be loaded, if any."""
    candidate = path or model_path()
    if not candidate.is_file():
        return "is missing"
    if candidate.stat().st_size < MIN_VALID_MODEL_BYTES:
        return f"is too small ({candidate.stat().st_size} bytes; expected at least {MIN_VALID_MODEL_BYTES} bytes)"
    return None


def download_official_model(destination: Path | None = None) -> Path:
    """Download standard YOLOv8n weights into ``models/`` using Ultralytics.

    The download is first made in a temporary directory. A failed download can
    therefore never leave a partial model at the project model path.
    """
    target = destination or model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is not installed. Install requirements.txt first.") from exc

    original_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="missing-child-yolo-") as temporary_directory:
        try:
            os.chdir(temporary_directory)
            YOLO(MODEL_FILENAME)  # Supported Ultralytics download/load mechanism.
        except Exception as exc:
            raise RuntimeError(
                "Could not download the official YOLOv8n model. Check internet access, then run "
                "`python services/detector.py --download` again."
            ) from exc
        finally:
            os.chdir(original_directory)

        downloaded = Path(temporary_directory) / MODEL_FILENAME
        reason = model_file_status(downloaded)
        if reason:
            raise RuntimeError(f"Ultralytics returned an invalid YOLO model: {reason}.")
        os.replace(downloaded, target)
    return target


def get_detector(download_if_needed: bool = True):
    """Return local YOLOv8n, recovering missing/invalid official weights once."""
    path = model_path()
    reason = model_file_status(path)
    if reason:
        if not download_if_needed:
            raise FileNotFoundError(
                f"YOLO model {reason}: {path}. Run `python services/detector.py --download` "
                "to fetch the official Ultralytics YOLOv8n weights."
            )
        print(f"Local YOLO model {reason}; obtaining official {MODEL_FILENAME}.")
        path = download_official_model(path)

    try:
        from ultralytics import YOLO
        return YOLO(str(path))
    except (EOFError, RuntimeError, ValueError, OSError) as exc:
        raise RuntimeError(
            f"YOLO could not load {path}. Run `python services/detector.py --download` "
            "to obtain an official replacement."
        ) from exc


def main() -> None:
    import sys

    if "--download" in sys.argv:
        saved = download_official_model()
        print(f"YOLO model saved: {saved}")
    else:
        get_detector()
        print("YOLO MODEL OK")


if __name__ == "__main__":
    main()
