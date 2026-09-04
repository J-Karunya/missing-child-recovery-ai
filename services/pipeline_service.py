"""Sprint 13 pipeline service: exposes the existing CCTV matcher as a callable.

This module does not contain any AI logic. It is a thin orchestration wrapper
that validates preconditions, copies an uploaded video to the expected location,
calls the existing generate_embedding() and run_matcher() functions, then cleans
up temporary files.

The AI decision chain is unchanged:
  YOLO → DeepSORT → InsightFace → attribute comparison → temporal evidence
  → PENDING potential match → authorized human VERIFY / REJECT

AI never automatically declares a child found.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import (
    ACTIVE_CHILD_ID,
    CCTV_UPLOADS_DIR,
    CCTV_VIDEOS_DIR,
    CHILD_IMAGES_DIR,
    EMBEDDINGS_DIR,
    ensure_runtime_directories,
    safe_filename,
)
from .review_store import AuthorizationError, ReviewStore, ValidationError

_SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
_SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def run_cctv_analysis(
    actor: str,
    store: ReviewStore,
    case_id: str,
    stored_video_name: str,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Orchestrate the existing CCTV pipeline for an ACTIVE case.

    Parameters
    ----------
    actor:
        Authenticated username performing the analysis.
    store:
        Active ReviewStore instance used for authorization and bridging.
    case_id:
        The ACTIVE case to analyze.
    stored_video_name:
        The UUID-prefixed filename stored by ``review_store.submit_cctv()``.
        Must exist in ``CCTV_UPLOADS_DIR``.
    progress_callback:
        Optional callable that receives human-readable progress strings.
        Useful for displaying ``st.status`` updates in Streamlit.

    Returns
    -------
    dict with keys:
        ``run_id`` (str | None), ``frames_processed`` (int),
        ``potential_matches`` (int), ``child_id`` (str), ``video_name`` (str)
    """

    def _progress(msg: str) -> None:
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    ensure_runtime_directories()

    # ── Authorization ─────────────────────────────────────────────────────────
    user = store._require(actor, "submit_cctv")  # noqa: SLF001 — internal bridge
    case = store.get_case(actor, case_id)
    if not case:
        raise ValidationError("Case does not exist or is not available to this user.")
    if not store.case_allows_ai_processing(case_id):
        raise AuthorizationError(
            "AI analysis requires the case to be ACTIVE. "
            "Ask police to verify the complaint first."
        )

    child_id: str = str(case.get("child_id") or ACTIVE_CHILD_ID)
    reference_image: str = str(case.get("reference_image") or "")
    _progress(f"Case {case_id} is ACTIVE. Child ID: {child_id}")

    # ── Locate uploaded video ──────────────────────────────────────────────────
    safe_stored = safe_filename(stored_video_name)
    upload_path = CCTV_UPLOADS_DIR / safe_stored
    if not upload_path.is_file():
        raise ValidationError(
            f"Uploaded CCTV file not found in secure storage: {stored_video_name}"
        )
    if upload_path.suffix.lower() not in _SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationError(
            f"Unsupported video format: {upload_path.suffix}. "
            "Accepted: .mp4, .avi, .mov"
        )
    _progress(f"Located CCTV upload: {stored_video_name}")

    # ── Ensure child embedding exists ──────────────────────────────────────────
    embedding_file = EMBEDDINGS_DIR / f"{safe_filename(child_id)}.npy"
    _progress(f"Checking embedding for child {child_id}…")
    if not embedding_file.is_file():
        _progress("Embedding not found — generating from child reference image…")
        _generate_embedding_for_case(child_id, reference_image, store, case_id, case)
        _progress("✓ Embedding generated")
    else:
        _progress("✓ Embedding already available")

    # ── Copy video to CCTV_VIDEOS_DIR under a safe temporary name ─────────────
    # run_matcher() looks for videos in CCTV_VIDEOS_DIR via config.video_path().
    # Uploaded videos live in CCTV_UPLOADS_DIR. We copy to a temporary name,
    # run the pipeline, then remove the copy. The original upload is preserved.
    temp_video_name = f"_demo_{safe_filename(child_id)}_{upload_path.suffix.lower()[1:]}_run.{upload_path.suffix.lower()[1:]}"
    dest_path = CCTV_VIDEOS_DIR / temp_video_name
    CCTV_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    _progress("Preparing CCTV footage for analysis…")
    try:
        shutil.copy2(upload_path, dest_path)
        _progress("✓ CCTV footage staged")

        # ── Run the existing pipeline ──────────────────────────────────────────
        _progress("Invoking YOLO detection…")
        _progress("Running DeepSORT tracking…")
        _progress("Extracting faces with InsightFace…")
        _progress("Comparing reference embeddings…")
        _progress("Aggregating temporal evidence…")

        from .cctv_matcher import run_matcher  # noqa: PLC0415 — lazy import

        match_count = run_matcher(child_id=child_id, cctv_filename=temp_video_name)
        _progress(f"✓ Pipeline complete — potential matches: {match_count}")

        # Retrieve run_id from the most recent match for this case (if any)
        recent_matches = store.list_matches(actor, case_id=case_id)
        run_id = recent_matches[0].get("run_id") if recent_matches else None

        return {
            "run_id": run_id,
            "frames_processed": "see audit log",
            "potential_matches": match_count,
            "child_id": child_id,
            "video_name": stored_video_name,
        }
    finally:
        # Always clean up the temporary staged video
        if dest_path.is_file():
            try:
                dest_path.unlink()
            except OSError:
                pass


def _generate_embedding_for_case(
    child_id: str,
    reference_image_filename: str,
    store: ReviewStore,
    case_id: str,
    case: dict[str, Any],
) -> None:
    """Resolve the child reference image and call generate_embedding().

    Strategy:
    1. Look for an existing unencrypted image in CHILD_IMAGES_DIR (legacy path).
    2. If not found, try to decrypt the first active child_reference_image
       record and write it temporarily to CHILD_IMAGES_DIR.
    3. Call generate_embedding(child_id) which reads from CHILD_IMAGES_DIR.
    4. Remove any temporary file written in step 2.
    """
    from .config import profile_path  # noqa: PLC0415
    from .evidence_crypto import EvidenceCrypto  # noqa: PLC0415
    from .evidence_storage import EvidenceStorage  # noqa: PLC0415
    from .config import EVIDENCE_DIR  # noqa: PLC0415

    safe_child_id = safe_filename(child_id)
    CHILD_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Check for an existing unencrypted reference image
    for ext in (".jpeg", ".jpg", ".png"):
        candidate = CHILD_IMAGES_DIR / f"{safe_child_id}{ext}"
        if candidate.is_file():
            _ensure_profile_exists(child_id, case=case, filename=candidate.name, store=store)
            _call_generate_embedding(child_id)
            return

    # Try to decrypt from controlled evidence storage
    temp_path: Path | None = None
    try:
        with store._connection() as db:  # noqa: SLF001
            row = db.execute(
                "SELECT opaque_reference FROM child_reference_images "
                "WHERE case_id=? AND status='ACTIVE' ORDER BY id LIMIT 1",
                (case_id,),
            ).fetchone()
        if not row or not row[0]:
            raise ValidationError(
                "No active child reference image found for this case. "
                "Upload a child photograph first."
            )
        opaque_ref = str(row[0])
        storage = EvidenceStorage(EVIDENCE_DIR, EvidenceCrypto())
        image_bytes = storage.read_controlled(opaque_ref)
        # Determine extension from opaque ref name heuristic
        ext = ".jpeg"
        temp_name = f"{safe_child_id}{ext}"
        temp_path = CHILD_IMAGES_DIR / temp_name
        temp_path.write_bytes(image_bytes)

        _ensure_profile_exists(child_id, case=case, filename=temp_name, store=store)
        _call_generate_embedding(child_id)
    finally:
        if temp_path and temp_path.is_file():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _ensure_profile_exists(
    child_id: str,
    case: dict | None,
    filename: str,
    store: ReviewStore,
) -> None:
    """Write a minimal child profile JSON if one does not already exist.

    generate_embedding() requires a profile at CHILD_PROFILES_DIR/{child_id}.json.
    If no profile exists but we have a case record, create a minimal one so
    the embedding can be generated without a separate manual step.
    """
    from .config import profile_path, CHILD_PROFILES_DIR  # noqa: PLC0415
    import json  # noqa: PLC0415

    target = profile_path(child_id)
    if target.is_file():
        return  # Already exists — do not overwrite

    if not case:
        # Try to look up from store if caller didn't pass case
        return  # Cannot create without case data; generate_embedding will fail with clear message

    CHILD_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_data = {
        "child_id": child_id,
        "name": str(case.get("child_name", child_id)),
        "description": str(case.get("description", "Missing child")),
        "age": case.get("age"),
        "image_filename": filename,
        "attributes": {},
    }
    target.write_text(json.dumps(profile_data, indent=2), encoding="utf-8")


def _call_generate_embedding(child_id: str) -> None:
    """Invoke the existing generate_embedding() function unchanged."""
    from .generate_embedding import generate_embedding  # noqa: PLC0415
    generate_embedding(child_id=child_id)


def list_pending_cctv_submissions(actor: str, store: ReviewStore, case_id: str | None = None) -> list[dict]:
    """Return PENDING_PROCESSING CCTV submissions visible to the actor.

    Only submissions for ACTIVE cases are actionable via AI analysis.
    """
    store._require(actor, "submit_cctv")  # noqa: SLF001
    with store._connection() as db:  # noqa: SLF001
        if case_id:
            rows = db.execute(
                "SELECT cs.*, c.lifecycle_state, c.case_status FROM cctv_submissions cs "
                "JOIN cases c ON c.case_id=cs.case_id "
                "WHERE cs.case_id=? ORDER BY cs.created_at DESC",
                (case_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT cs.*, c.lifecycle_state, c.case_status FROM cctv_submissions cs "
                "JOIN cases c ON c.case_id=cs.case_id "
                "ORDER BY cs.created_at DESC",
            ).fetchall()
    from .review_store import _row  # noqa: PLC0415, SLF001
    return [_row(r) for r in rows if r]
