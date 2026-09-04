"""CCTV pipeline: detection -> tracking -> face comparison -> human review.

This prototype only creates PENDING potential-match records. A score is evidence
for an authorized human reviewer, never confirmation that a child was found.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import cv2
import numpy as np

try:
    from .attribute_extractor import extract_attributes
    from .config import ACTIVE_CHILD_ID, ALERTS_DIR, EVIDENCE_DIR, CCTV_PROGRESS_INTERVAL, DEFAULT_VIDEO_NAME, MAX_CCTV_VIDEO_BYTES, MIN_TRACK_OBSERVATIONS, POTENTIAL_MATCH_THRESHOLD, embedding_path, ensure_runtime_directories, parsed_profile_path, video_path
    from .detector import get_detector
    from .match_engine import build_match_scores
    from .lighting_detector import classify_lighting
    from .temporal_evidence import PotentialMatchRegistry, TrackEvidenceAggregator
    from .tracker import create_tracker
    from .utils import load_embedding_file, log_audit_event, log_potential_match
except ImportError:  # Supports `python services/cctv_matcher.py`.
    from attribute_extractor import extract_attributes
    from config import ACTIVE_CHILD_ID, ALERTS_DIR, EVIDENCE_DIR, CCTV_PROGRESS_INTERVAL, DEFAULT_VIDEO_NAME, MAX_CCTV_VIDEO_BYTES, MIN_TRACK_OBSERVATIONS, POTENTIAL_MATCH_THRESHOLD, embedding_path, ensure_runtime_directories, parsed_profile_path, video_path
    from detector import get_detector
    from match_engine import build_match_scores
    from lighting_detector import classify_lighting
    from temporal_evidence import PotentialMatchRegistry, TrackEvidenceAggregator
    from tracker import create_tracker
    from utils import load_embedding_file, log_audit_event, log_potential_match

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def _load_face_app():
    try:
        from insightface.app import FaceAnalysis
    except ImportError as exc:
        raise RuntimeError("InsightFace is not installed. Install requirements.txt first.") from exc
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1)
    return app


def _load_profile(child_id: str) -> dict:
    path = parsed_profile_path(child_id)
    if not path.is_file():
        raise FileNotFoundError(f"Parsed profile not found: {path}. Run profile_builder.py first.")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Parsed profile is unreadable: {path}. Run profile_builder.py again.") from exc
    if profile.get("child_id") != child_id:
        raise ValueError("Profile child_id does not match MISSING_CHILD_ID.")
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        raise ValueError("Parsed profile is missing a valid child name. Run profile_builder.py again.")
    if not isinstance(profile.get("description"), str):
        raise ValueError("Parsed profile is missing its description. Run profile_builder.py again.")
    attributes = profile.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("Child profile has no structured attributes. Run profile_builder.py with the configured LLM first.")
    return profile


def _detections(results) -> list[tuple[list[int], float, str]]:
    detections = []
    for result in results:
        for box in result.boxes:
            if int(box.cls[0]) != 0:  # COCO person
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append(([x1, y1, x2 - x1, y2 - y1], float(box.conf[0]), "person"))
    return detections


def run_matcher(child_id: str = ACTIVE_CHILD_ID, cctv_filename: str = DEFAULT_VIDEO_NAME) -> int:
    ensure_runtime_directories()
    source_path = video_path(cctv_filename)
    if source_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f"Unsupported CCTV format: {source_path.suffix}")
    if not source_path.is_file():
        raise FileNotFoundError(f"CCTV video not found: {source_path}")
    if source_path.stat().st_size > MAX_CCTV_VIDEO_BYTES:
        raise ValueError(f"CCTV video exceeds the configured {MAX_CCTV_VIDEO_BYTES}-byte limit: {source_path}")

    profile = _load_profile(child_id)
    child_embedding = load_embedding_file(embedding_path(child_id))
    if child_embedding.shape[0] != 512:
        raise ValueError("Embedding has an unexpected size. Run generate_embedding.py again.")

    run_id = uuid4().hex
    detector = get_detector()
    tracker = create_tracker()
    face_app = _load_face_app()
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV could not open CCTV video: {source_path}")

    frame_number = 0
    total_frames = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    potential_match_count = 0
    evidence_file_count = 0
    observed_track_ids: set[int] = set()
    face_track_ids: set[int] = set()
    lighting_conditions: set[str] = set()
    emitted_matches = PotentialMatchRegistry()
    evidence_aggregator = TrackEvidenceAggregator(MIN_TRACK_OBSERVATIONS)
    log_audit_event({"run_id": run_id, "action": "matcher_started", "child_id": child_id, "cctv_source": source_path.name, "outcome": "PENDING_REVIEW_ONLY"})
    print(f"Monitoring child ID: {child_id} ({profile['name']})")
    print(f"Run ID: {run_id}")
    print("All results are potential matches pending authorized human verification.")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_number += 1
            lighting_conditions.add(classify_lighting(frame))
            if frame_number % CCTV_PROGRESS_INTERVAL == 0 or (total_frames and frame_number == total_frames):
                print(f"Processing frame {frame_number}/{total_frames or '?'}")
            tracks = tracker.update_tracks(_detections(detector(frame, verbose=False)), frame=frame)
            for track in tracks:
                observed_track_ids.add(track.track_id)
                if not track.is_confirmed():
                    continue
                x1, y1, x2, y2 = map(int, track.to_ltrb())
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                person_crop = frame[y1:y2, x1:x2]
                if person_crop.size == 0:
                    continue
                for face in face_app.get(person_crop):
                    face_track_ids.add(track.track_id)
                    candidate = np.asarray(face.embedding, dtype=np.float32)
                    if candidate.shape != child_embedding.shape:
                        continue
                    candidate_norm = float(np.linalg.norm(candidate))
                    if candidate_norm == 0:
                        continue
                    cosine = float(np.clip(np.dot(child_embedding, candidate / candidate_norm), 0.0, 1.0))
                    scores = build_match_scores(cosine, profile["attributes"], extract_attributes(person_crop))
                    aggregate = evidence_aggregator.add(track.track_id, scores, frame_number)
                    if not aggregate["ready"] or aggregate["overall_score"] < POTENTIAL_MATCH_THRESHOLD:
                        continue
                    if not emitted_matches.mark_if_new(child_id, track.track_id):
                        break
                    evidence_path = ALERTS_DIR / f"{child_id}_track_{track.track_id}_frame_{frame_number}.jpg"
                    if not cv2.imwrite(str(evidence_path), frame):
                        raise IOError(f"Could not save evidence image: {evidence_path}")
                    metadata_path = evidence_path.with_suffix(".json")
                    event = {
                        "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "child_id": child_id,
                        "track_id": track.track_id, "frame_number": frame_number,
                        "face_score": aggregate["face_score"], "clothing_score": aggregate["clothing_score"],
                        "accessory_score": aggregate["accessory_score"], "physical_feature_score": aggregate["physical_feature_score"],
                        "attribute_score": scores["attribute_score"], "overall_score": aggregate["overall_score"],
                        "matched_attributes": aggregate["matched_attributes"], "mismatched_attributes": aggregate["mismatched_attributes"],
                        "unknown_attributes": aggregate["unknown_attributes"], "observation_count": aggregate["observation_count"],
                        "evidence_reasons": {"matched": aggregate["matched_attributes"], "mismatched": aggregate["mismatched_attributes"], "unknown": aggregate["unknown_attributes"]},
                        "verification_status": "PENDING", "status": "PENDING", "evidence_image": str(evidence_path),
                        "evidence_metadata": str(metadata_path), "cctv_source": source_path.name,
                        "lighting_condition": classify_lighting(frame),
                    }
                    metadata_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
                    log_potential_match(event)
                    # The AI pipeline remains PENDING-only.  If the child is linked to
                    # a managed case, store the same controlled event for authorized
                    # review and local notification delivery.  Evidence logging still
                    # succeeds when no case-management record exists.
                    try:
                        from services.review_store import ReviewStore, ValidationError
                        stored_match = ReviewStore().record_pipeline_match_for_child(event)
                        # Existing plaintext evidence remains compatible when no key is
                        # configured. With a configured key, persist opaque encrypted
                        # bytes and update only the controlled database reference.
                        if stored_match:
                            from services.evidence_crypto import EvidenceCrypto
                            from services.evidence_storage import EvidenceStorage
                            try:
                                encrypted = EvidenceStorage(EVIDENCE_DIR, EvidenceCrypto())
                                reference = encrypted.store(stored_match["id"], evidence_path.read_bytes())
                                ReviewStore().set_encrypted_evidence_reference(stored_match["id"], reference)
                                evidence_path.unlink(missing_ok=True)
                            except ValidationError:
                                pass
                    except Exception as exc:
                        log_audit_event({"run_id": run_id, "action": "review_store_bridge_failed", "child_id": child_id, "outcome": str(exc)[:300]})
                    potential_match_count += 1
                    evidence_file_count += 2
                    print(f"Potential Match Detected | child={child_id} track={track.track_id} score={aggregate['overall_score']}% | Pending Verification")
                    break
    finally:
        capture.release()
        # This prototype does not open any OpenCV windows. Some headless OpenCV
        # builds do not implement HighGUI, so cleanup must not mask a completed
        # CCTV run with an unrelated ``cvDestroyAllWindows`` error.
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
    log_audit_event({"run_id": run_id, "action": "matcher_completed", "child_id": child_id, "cctv_source": source_path.name, "outcome": f"frames={frame_number}; potential_matches={potential_match_count}"})
    print("========== SUMMARY ==========")
    print(f"Child ID: {child_id}")
    print(f"Child Name: {profile['name']}")
    print(f"Video: {source_path.name}")
    print(f"Frames Processed: {frame_number}")
    print(f"Tracks Observed: {len(observed_track_ids)}")
    print(f"Tracks With Faces: {len(face_track_ids)}")
    print(f"Potential Matches: {potential_match_count}")
    print(f"Evidence Files: {evidence_file_count}")
    print(f"Run ID: {run_id}")
    print(f"Lighting Observed: {', '.join(sorted(lighting_conditions)) or 'UNKNOWN'}")
    print("=============================")
    if potential_match_count == 0:
        print("No potential match crossed the configured verification threshold.")
    return potential_match_count


def main() -> None:
    run_matcher()


if __name__ == "__main__":
    main()
