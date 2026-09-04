"""Generate one validated, normalized embedding for the active child profile."""

from __future__ import annotations

import json
import os
import tempfile

import cv2
import numpy as np

try:
    from .config import ACTIVE_CHILD_ID, CHILD_IMAGES_DIR, embedding_path, ensure_runtime_directories, profile_path, safe_filename
except ImportError:
    from config import ACTIVE_CHILD_ID, CHILD_IMAGES_DIR, embedding_path, ensure_runtime_directories, profile_path, safe_filename


def _load_face_app():
    try:
        from insightface.app import FaceAnalysis
    except ImportError as exc:
        raise RuntimeError("InsightFace is not installed. Install requirements.txt first.") from exc
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1)
    return app


def _face_area(face) -> float:
    return float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))


def generate_embedding(child_id: str = ACTIVE_CHILD_ID) -> tuple[str, tuple[int, ...]]:
    ensure_runtime_directories()
    raw_profile_path = profile_path(child_id)
    if not raw_profile_path.is_file():
        raise FileNotFoundError(f"Child profile not found: {raw_profile_path}")
    try:
        profile = json.loads(raw_profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Child profile is unreadable: {raw_profile_path}. Correct the JSON and try again.") from exc
    if profile.get("child_id") != child_id:
        raise ValueError("Profile child_id does not match the configured active child ID.")
    if not isinstance(profile.get("name"), str) or not profile["name"].strip() or not isinstance(profile.get("description"), str):
        raise ValueError("Child profile must include a valid child_id, name, and description. Run profile_builder.py after correcting it.")
    image_name = safe_filename(profile.get("image_filename") or os.getenv("CHILD_IMAGE_FILE", "child1.jpeg"))
    image_path = CHILD_IMAGES_DIR / image_name
    if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Child image must be a JPG, JPEG, or PNG file.")
    if not image_path.is_file():
        raise FileNotFoundError(f"Child image not found: {image_path}")
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"OpenCV could not read child image: {image_path}")
    faces = _load_face_app().get(image)
    if not faces:
        raise ValueError("No face detected in child image; select a clearer authorized image.")
    embedding = np.asarray(max(faces, key=_face_area).embedding, dtype=np.float32)
    norm = float(np.linalg.norm(embedding))
    if embedding.ndim != 1 or embedding.size == 0 or not np.isfinite(embedding).all() or norm == 0:
        raise ValueError("InsightFace returned an invalid embedding; no file was written.")
    embedding /= norm
    destination = embedding_path(child_id)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".npy", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        np.save(temp_path, embedding)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return str(destination), embedding.shape


def main() -> None:
    print(f"Generating embedding for child ID: {ACTIVE_CHILD_ID}")
    saved_path, shape = generate_embedding()
    print(f"Embedding saved safely: {saved_path}")
    print(f"Embedding shape: {shape}")


if __name__ == "__main__":
    main()
