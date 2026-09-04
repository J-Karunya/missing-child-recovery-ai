# Interview Guide

## Problem and solution

Sprint 12 separates a family report from an active investigation: only an
authorized police/admin verification activates a case for authorized CCTV
processing. Its parent-assisted age-progression boundary is research-only,
review-gated, and never represents a generated candidate as a real photograph
or deterministic genetic prediction.

Sprint 13 demonstrates the same safeguarded workflow entirely in Streamlit:
parents submit reports and controlled references, police activate verified
cases and submit authorized CCTV, the existing AI pipeline produces only
PENDING evidence, reviewers make terminal decisions, and administrators see
authorized audit/health summaries. It remains a research prototype, not a
production police system.

Missing-child investigations may involve authorized CCTV footage, but a model score cannot identify a person safely on its own. This project is a decision-support prototype: it produces explainable PENDING potential matches, then gives authorized people a review dashboard. It never automatically states that a child is recovered.

## Architecture in one minute

An authorized reference image becomes a normalized InsightFace embedding. YOLO detects people in CCTV frames, DeepSORT keeps each person’s track ID stable, and InsightFace compares visible faces using cosine similarity. Optional LLM parsing converts a parent description into `true`, `false`, or `null` attributes; unknown means unknown, not false. The match engine explains component scores and temporal evidence requires several observations. Sprint 4 stores PENDING records in SQLite and exposes role-aware Streamlit review screens.

## Why these choices

| Question | Concise answer |
|---|---|
| Why YOLO? | It efficiently finds people in each CCTV frame. |
| Why DeepSORT? | It associates detections over time, making multi-frame evidence possible. |
| Why InsightFace? | It produces robust face embeddings for comparison. |
| Why cosine similarity? | It compares the direction of normalized embedding vectors consistently. |
| Why temporal evidence? | A single frame can be poor quality; several observations reduce accidental alerts. |
| Why preserve unknown attributes? | `null` avoids turning unavailable information into a false mismatch. |
| Why not let AI decide? | Face/video scores are evidence, not proof; authorized human verification is required. |
| Why SQLite? | It is lightweight, relational, and suitable for a local prototype without a database server. |
| Why Streamlit? | It quickly creates a clear research/demo interface while keeping the AI code in services. |

## Sprints

- **Sprint 1:** profile validation, controlled paths, InsightFace reference embedding.
- **Sprint 2:** YOLO + DeepSORT + CCTV face-comparison pipeline with PENDING evidence.
- **Sprint 3:** optional semantic profile context, `true`/`false`/`null`, explainable scoring, and temporal aggregation.
- **Sprint 4:** SQLite cases/evidence/audit trail, local prototype roles, controlled CCTV intake, and Streamlit review dashboard.
- **Sprint 5:** Argon2 login, session expiry, account state/lockout, central service authorization, parent isolation, secure evidence lookup, safe retention reporting, and security testing.
- **Sprint 6:** database-backed local notifications, parent-safe templates, multi-station routing using existing assignments, audit trails, and camera-observation foundation.

## Security, privacy, and limitations

Only authorized, case-associated input belongs in the prototype. Secrets are environment variables; passwords are Argon2 hashes; paths/extensions/sizes are checked; parent views are intentionally restricted; and raw embeddings are not presented in dashboard logs. Sprint 6 notifications are local in-app records, not real messages. The project is still not production ready: it lacks MFA, HTTPS, encryption, malware scanning, chain-of-custody processes, approved retention enforcement, calibrated scores, live CCTV, and approved external delivery.

## Sprint 6 interview questions

| Question | Concise answer |
|---|---|
| How does the system notify parents? | It creates a local, in-app notification for the linked parent with cautious wording that a potential match is under authorized review. |
| Why not say the child was found immediately? | The AI result is only PENDING evidence. A human reviewer must verify it, and even then the parent wording stays conservative. |
| How do multiple stations receive updates? | The original case station and only explicitly active records in `case_station_assignments` are selected. |
| How do you prevent unauthorized stations seeing a case? | Service-layer station/case checks apply both to the case itself and notification recipient selection. |
| How are duplicate notifications prevented? | SQLite has a unique case + match + recipient + notification-type constraint. |
| What information differs for parents and police? | Parents get no scores, evidence, paths, stations, location, notes, or reviewer identity. Staff receive controlled internal details and evidence IDs. |
| Can the system provide live GPS location? | No. It can associate a potential match with the latest observed authorized CCTV camera/station, but that is not GPS tracking or guaranteed live location. |
| How are notifications audited? | Creation, local send/failure, and read actions are stored in the existing audit log; pipeline events use SYSTEM, not a fabricated human identity. |
| What if delivery fails? | The database row becomes FAILED with a safe reason and an audit entry; the match/review status is not changed. |
| How would SMS/push be added later? | Implement an approved provider behind the `NotificationProvider` interface, keep credentials in environment-managed configuration, and explicitly enable it after security/governance review. |

## Future enhancements

Sprint 5 should harden secure authentication, evidence protection, moderated intake, and operational review workflows. Later phases could add protected production storage, authorized camera integrations, and reporting, without changing the core principle that AI produces potential matches and humans make final decisions.
