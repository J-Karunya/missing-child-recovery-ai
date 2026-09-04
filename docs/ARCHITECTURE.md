# Architecture

```text
Authorized case/photo
  -> InsightFace reference embedding
  -> Authorized CCTV frames
  -> YOLO person boxes
  -> DeepSORT stable track IDs
  -> InsightFace face comparison + cosine similarity
  -> optional attributes + explainable score
  -> temporal evidence
  -> PENDING potential match
  -> SQLite case/evidence/audit record
  -> authenticated reviewer
  -> KEEP PENDING / VERIFY / REJECT
  -> authorized local notification records
```

## Module responsibilities

| Module | Input → output | Security role |
|---|---|---|
| `generate_embedding.py` | Authorized photo → normalized face vector | Validates controlled image/profile input. |
| `detector.py`, `tracker.py`, `cctv_matcher.py` | CCTV → person/track/face evidence | Keeps AI results as PENDING only. |
| `match_engine.py`, `temporal_evidence.py` | Observations → explainable multi-frame score | Unknown remains unknown, not a mismatch. |
| `review_store.py` | Authenticated request → authorized SQLite record | Parameterized SQL, foreign keys, role/case checks, audits. |
| `auth.py` | Credential/session input → Argon2 verification/non-secret session data | Never stores or returns plaintext passwords. |
| `retention.py` | Authorized retention request → dry-run report or explicit cleanup | Default is report-only. |
| `notification_service.py` | PENDING/VERIFY/REJECT event → deduplicated, role-safe local notification | Uses only case-authorized stations; default delivery is SQLite, not real messaging. |
| `dashboard/` | Authenticated user → role-safe Streamlit pages | Does not contain AI inference. |

The dashboard is not an AI model. It is the human-review layer after the pipeline has created a PENDING potential match.

Sprint 7 adds audited lifecycle transitions, logical evidence lifecycle state, Argon2 password change/reset controls, an MFA-ready interface that never accepts a fake factor, and local backup/configuration-check utilities. None alters AI matching.

Sprint 6 adds `notifications` and `match_observations` to the same SQLite boundary. Parent wording is centralized and conservative. Staff wording uses controlled evidence IDs, never raw file paths. A last observed camera is a camera-associated CCTV observation, not GPS or a claim of live tracking.
