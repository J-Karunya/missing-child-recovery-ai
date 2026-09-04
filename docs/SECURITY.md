# Security Approach

## IMPLEMENTED NOW

Sprint 12 keeps child, parent/guardian, and generated references separate and
uses controlled encrypted opaque references. Parent access is case-isolated;
parent-facing data excludes internal police notes, reviewer identity, evidence
paths, image bytes, CCTV sources, scores, and embeddings. Reference deletion is
explicit, logical, audited, and blocked by legal hold.

This is a sensitive biometric prototype and must only process authorized, case-associated images and CCTV footage.

- Secrets are read from environment variables; API keys are not hardcoded.
- `.env`, images, CCTV files, embeddings, generated alerts, and logs are excluded from Git.
- Configuration accepts only simple media filenames and uses project-relative controlled directories, reducing path traversal risk.
- Image/video extensions and embedding shape/content are validated before use.
- CCTV inputs have a configurable maximum file size and remain restricted to the controlled video directory; uploaded files are not executed because this prototype has no upload endpoint.
- Evidence is stored under the controlled `data/alerts` directory and limited to what an authorized reviewer needs.
- Structured match logs and minimal start/completion audit records include a run ID; raw embeddings are never written to those logs.
- Result status is always `PENDING`; human verification prevents an AI score from becoming an automated declaration or notification.
- The prototype limits personal-data exposure by using local files and recording only necessary case/track/evidence fields.
- Sprint 4 stores controlled evidence references and case/review audit records in SQLite. Evidence is resolved only from the controlled alerts folder, never from a dashboard-supplied path.
- Controlled CCTV intake allows only MP4, AVI, and MOV under a configured size limit; received footage stays `PENDING_PROCESSING` and is not automatically trusted or processed.
- Parent-safe views exclude evidence, CCTV sources, score breakdowns, reviewer notes, identities, and audit records.
- Sprint 5 adds Argon2 password hashes, active-account checks, generic failed-login responses, temporary lockouts, logout, and short-lived non-secret sessions.
- Service-layer role/case checks, parameterized SQL, foreign keys, controlled evidence lookup, generated upload names, basic video-signature checks, and dry-run retention reports further protect local data.
- Sprint 6 keeps delivery local by default. Notification recipients are limited to the linked parent and users at the original or explicitly active assigned stations; duplicate rows are blocked by a database uniqueness constraint.
- Parent notifications use centralized safe templates and omit scores, evidence, internal notes, reviewer identity, station data, raw paths, and location. Staff receive controlled evidence references, not filesystem paths.
- Notification metadata is bounded and rejects secret/credential/embedding-style keys. Notification reads, creation, sends, and failures are audited. Camera observations require an existing active authorized camera and are not represented as GPS.

Do not publish evidence, embeddings, raw profiles, or source videos. Apply applicable law, consent, policy, and organizational procedures before any real-world use.

Sprint 7 adds explicit lifecycle transitions, logical evidence deletion requiring admin confirmation, an MFA-ready boundary, non-secret configuration checks, and timestamped local SQLite backups. Audit logs are append-only through the application API; this still is not production certification.

## PLANNED FUTURE

Sprint 5 is a secured prototype, not a production security certification. It still lacks MFA, password resets, HTTPS, secure server-side session storage, encryption at rest/in transit, full malware scanning, legal-hold handling, approved automated retention, production evidence hosting, deployment hardening, penetration testing, and formal legal/privacy review.
