# Complete Workflow

## IMPLEMENTED NOW

Sprint 12 adds: parent report → police complaint/reference verification →
`ACTIVE` case → authorized CCTV → `PENDING` potential match → human
`VERIFY`/`REJECT`. Parent recent photos are controlled supporting inputs for an
age-progression candidate; candidates remain `PENDING_REVIEW` until an
authorized reviewer approves them.

Sprint 13 makes that flow available through the authenticated dashboard:

Parent report + missing-child photo + optional guardian reference →
`PENDING_POLICE_VERIFICATION` → police verification → `ACTIVE` → authorized
CCTV upload → **Run AI Analysis** → existing YOLO/DeepSORT/InsightFace flow →
`PENDING` potential match → reviewer `VERIFY`/`REJECT` → parent-safe
notification and admin audit record.

| Step | Input | Processing | Output | Responsible module |
|---|---|---|---|---|
| 1. Case information | Child ID, name, age, optional description | Validates the basic case profile. | Raw profile JSON | `profile_builder.py` |
| 2. Child image | Authorized JPG/PNG filename | Validates that the file is in the controlled image folder. | Readable image | `generate_embedding.py` |
| 3. Profile generation | Parent free-text description | Optional LLM extracts only explicit facts; an outage returns unknown values safely. | Parsed profile JSON | `profile_parser.py`, `profile_builder.py` |
| 4. Embedding generation | Child image | InsightFace picks a face, creates and normalizes an ArcFace vector. | `embeddings/MC001.npy` | `generate_embedding.py` |
| 5. CCTV input | Authorized video filename | Validates format, file-size limit, and controlled path; opens the video. | Video frames | `cctv_matcher.py` |
| 6. Person detection | One frame | YOLO detects COCO class `person`. | Bounding boxes | `detector.py` |
| 7. Tracking | Person boxes across frames | DeepSORT assigns a persistent ID. | Confirmed tracks | `tracker.py` |
| 8. Face recognition | A tracked person crop + child embedding | InsightFace creates a candidate vector; cosine similarity becomes face score. | Face score | `cctv_matcher.py` |
| 9. Attribute analysis | Person crop | Coarse top colour is attempted; unsupported/unreliable fields are `null`. | Observed attribute schema | `attribute_extractor.py` |
| 10. Match scoring | Face score, profile, observed attributes | Scores components, records matched/mismatched/unknown fields, and re-normalizes known evidence. | Explainable score result | `match_engine.py` |
| 11. Evidence creation | Passing aggregated track result | Saves one CCTV frame and JSON metadata with a run ID/evidence reasons; appends structured event and minimal audit logs. | Evidence files and PENDING event | `cctv_matcher.py`, `utils.py` |
| 12. Potential match | Track with at least three observations and threshold score | Deduplicates child + track for the current run. | `PENDING` Potential Match Detected | `cctv_matcher.py`, `temporal_evidence.py` |
| 13. Authorized notification | Stored PENDING/review decision | Creates deduplicated parent-safe and station-authorized in-app records. | Local `SENT` notification + system audit | `notification_service.py` |
| 14. Human verification | PENDING evidence | An authorized local prototype reviewer selects KEEP PENDING, VERIFY, or REJECT; VERIFY requires confirmation. | Reviewer-verified/Rejected/PENDING decision + conservative update + audit | `review_store.py`, dashboard |

DeepSORT and temporal aggregation avoid treating one noisy frame as a result and prevent dozens of duplicate alerts for the same person. `null` deliberately means “we do not know,” so it is never converted to a mismatch.

Each frame also receives a lightweight DAY/NIGHT label. It is metadata only: low-light or grayscale footage is not rejected or enhanced by the current sprint.

Sprint 4 does not change the first 12 AI steps. It adds a database-backed case/review layer after the PENDING event. The Streamlit UI presents only role-appropriate information: parents do not receive evidence, CCTV sources, internal scores, or reviewer notes.

Sprint 5 requires sign-in before a dashboard page is available. Sprint 6 keeps that boundary and adds local notification records only for a case parent and staff at the original/actively assigned station. The final chain is: **PENDING potential match → SQLite → authorized local notification → authenticated reviewer → explicit KEEP PENDING/VERIFY/REJECT → conservative follow-up + audit**. AI never performs the final transition.

## PLANNED FUTURE

Notifications, multiple cameras, live streams, public uploads, and automated police/parent communication remain outside the completed Sprint 5 scope.
