# Project Architecture

## IMPLEMENTED NOW

### Sprint 12 safety extension

Parent report → `PENDING_POLICE_VERIFICATION` → police complaint/reference
verification → `ACTIVE` → authorized CCTV processing. Child and guardian
references use encrypted opaque storage. Any age-progression candidate is an
AI-assisted research artifact, not a genetic prediction; it requires reviewer
approval before it becomes an additional, provenance-labelled InsightFace input.

### Sprint 13 demo orchestration

The authenticated Streamlit UI calls `pipeline_service.py` only after the
existing service-layer case gate confirms an `ACTIVE` case. The service stages
an authorized upload, obtains the existing child embedding when available, and
invokes the unchanged matcher. No UI route fabricates a detection or alters the
result: any actual AI result remains a `PENDING` potential match for reviewer
action.

### Problem and objective

Sprint 8 adds optional real TOTP MFA, hashed server-side prototype sessions, Fernet evidence-encryption and scanner abstractions, plus legal-hold protection. These controls sit after the unchanged AI pipeline and before controlled evidence access; they do not permit an AI result to leave PENDING without an authorized human review.

Missing-child cases need a careful way to search **authorized** CCTV footage without treating an AI score as proof. This local prototype creates explainable **Potential Match Detected** records for a human reviewer. It combines a reference-face embedding with only the profile details and CCTV attributes that are actually known.

```text
Parent / case worker
  -> Case registration: child photo + optional description
  -> AI Profile Understanding (optional LLM)
  -> Structured profile (true / false / null)
  -> InsightFace / ArcFace embedding

Authorized CCTV video -> YOLO person detection -> DeepSORT track ID
  -> InsightFace face comparison -> conservative attribute analysis
  -> Match engine -> temporal evidence aggregation
  -> Potential Match Detected (PENDING) -> human verification
```

### Major components and flow

| Component | Why it exists | Output |
|---|---|---|
| `profile_parser.py` | Turns free parent language into a consistent optional-attribute schema using an LLM when configured. | Attributes where `true` means present, `false` absent, `null` unknown. |
| `generate_embedding.py` | Converts the authorized child photograph to a normalized ArcFace vector. Embeddings permit comparison without repeatedly comparing raw pixels. | `<child_id>.npy` |
| YOLO (`detector.py`) | Quickly finds people in each CCTV frame. | Person boxes |
| DeepSORT (`tracker.py`) | Assigns stable track IDs so the same person can be assessed over time. | Tracks |
| InsightFace | Finds a face inside a person crop and creates a comparable embedding. Cosine similarity compares the direction of normalized embeddings. | Face similarity |
| `attribute_extractor.py` | Supplies conservative supporting visual evidence. At present it can only classify a coarse top colour; unsupported fields stay `null`. | Observed attributes |
| `match_engine.py` | Produces separate face, clothing, accessory, physical-feature, and overall scores plus evidence lists. | Explainable score result |
| `temporal_evidence.py` | Averages observations for a track and waits for multiple frames. | Aggregated track evidence |
| `cctv_matcher.py` | Orchestrates the complete authorized-video pipeline and saves evidence. | One PENDING event per child/track/run |
| `lighting_detector.py` | Labels frame brightness as DAY or NIGHT without treating grayscale or low-light footage as invalid. | Non-decisive run metadata |

Storage is project-relative: profiles are in `data/child_profiles`, parsed profiles in `data/parsed_profiles`, biometric vectors in `embeddings`, and controlled evidence in `data/alerts`. CSV logging is file-based in `data/logs/match_events.csv`; no database is introduced in Sprint 3.

### Matching design

The configurable default weights are face 70%, clothing 15%, accessories 10%, and physical features 5%. The overall score is a re-normalized weighted average of only score components that have usable evidence. This avoids the misleading assumption that a missing observation is negative evidence. These scores are uncalibrated prototype signals, not probabilities or identification proof.

Unknown parent attributes never affect a score. A known attribute that cannot be observed on CCTV is recorded as unknown, not a mismatch. This explains why `null` is essential: it prevents “not supplied” from becoming “no.”

### Human verification and security boundary

AI never changes a case to found. It emits `PENDING`; a later authorized review system may set `VERIFIED` or `REJECTED`. Evidence consists of a controlled frame, JSON metadata, and CSV event so a reviewer can inspect why a potential match was produced.

Secrets are environment variables, input media names are validated as simple filenames, and sensitive images, videos, embeddings, alerts, and logs are excluded by `.gitignore`. Only authorized case-associated footage should be processed. See [SECURITY.md](SECURITY.md).

Each run has a generated run ID. Evidence metadata and match logs record that ID, while `audit_events.csv` records start/completion lifecycle entries without copying biometric vectors.

## Sprint 4 review layer

Sprint 4 adds `services/review_store.py` and a Streamlit presentation layer under `dashboard/`. The repository owns SQLite validation, role checks, PENDING-only AI-match insertion, review transitions, evidence references, stations, cameras, controlled upload intake, and audit records. The dashboard calls that repository; it does not import or run YOLO, DeepSORT, or InsightFace.

```text
Existing matcher -> PENDING evidence/metadata
  -> review_store.py -> SQLite case/match/evidence/audit records
  -> Streamlit role-aware views -> authorized human review
```

Parents see only their linked case and parent-safe status. Internal scores, CCTV source, evidence, reviewer notes, and audit data remain restricted to operational roles. A registered camera location is only an **approximate location based on registered CCTV camera**, never live GPS.

## PLANNED FUTURE

Production authentication, encrypted storage, production role enforcement, Power BI, live/multi-camera CCTV, public uploads, notifications, live location, age progression, cloud deployment, malware scanning, and retention workflows are not implemented. Current limitations also include a coarse colour-only visual extractor, one local video at a time, no calibrated thresholds, and a manual human-review process.
