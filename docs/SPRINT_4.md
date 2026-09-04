# Sprint 4 — Authorized Review, Case Management, and Dashboard Foundation

## Objective

Sprint 4 adds a local review layer around the completed AI pipeline. YOLO, DeepSORT, InsightFace, matching, and temporal evidence remain unchanged. Their output is still a **PENDING Potential Match**; an authorized human may later choose KEEP PENDING, VERIFY, or REJECT.

## Implemented features

- SQLite storage at `data/database/missing_child_ai.db`.
- Case, user, potential-match, evidence, audit-log, CCTV-submission, station-assignment, and camera tables.
- Local prototype roles: ADMIN, POLICE, REVIEWER, and PARENT.
- Streamlit dashboard with role-aware Dashboard, Cases, Potential Matches, Evidence, CCTV Submission, Audit Logs (admin), Profile, and About pages.
- Explicit human review actions. VERIFY requires a confirmation checkbox. No AI action can create VERIFIED status.
- Controlled CCTV submission accepts only MP4, AVI, or MOV within the configured size limit and stores it as `PENDING_PROCESSING`.
- Parent-safe views remove internal scores, reviewer notes, video source, evidence, and audit data.
- Controlled evidence names are stored in SQLite and resolved only inside `data/alerts`; dashboard users never supply a filesystem path.

## Database schema

| Table | Purpose |
|---|---|
| `cases` | Validated child case data, case state, station and parent ownership reference. |
| `potential_matches` | AI-generated PENDING candidates and subsequent human-review state. |
| `evidence` | Controlled references to frame/metadata files for a match. |
| `users` | Local demo identities and roles. |
| `audit_logs` | Login selection, case, evidence, upload, station, and review actions. |
| `case_station_assignments` | Future-ready station ownership/assignment data. |
| `cameras` | Registered camera metadata only; it is not GPS/live tracking. |
| `cctv_submissions` | Controlled future intake records, always `PENDING_PROCESSING`. |

Foreign keys and indexes cover case/match status, run/track lookup, and audit-resource history.

## Review workflow

1. The existing matcher creates evidence and a PENDING potential match.
2. The review repository stores the candidate against an existing case.
3. An authorized police/reviewer/admin user opens restricted evidence and score reasons.
4. KEEP PENDING, VERIFY, or REJECT is selected with notes.
5. Every review action creates an audit record. “Verified Match” means **verified by an authorized reviewer**, never by AI.

Unknown attributes remain unknown; they are displayed separately from mismatches and never score as a negative fact.

## Roles

- **ADMIN:** local user management, all cases/matches, reviews, and audit logs.
- **POLICE:** cases and operational evidence for its station, reviews, camera/station information, and controlled CCTV submission.
- **REVIEWER:** assigned/station cases, restricted evidence, and review decisions.
- **PARENT:** only linked child-case status and parent-safe potential-match status.

## Security controls and limitations

This is not production authentication. The dashboard’s identity selector demonstrates intended permissions only. Production requires password hashing, MFA, secure sessions, HTTPS, server-enforced RBAC, secure secrets, encryption, malware scanning, moderation, chain of custody, and governance.

No police API, notification, SMS, email, live GPS, phone tracking, public image search, public CCTV uploads, cloud deployment, or automatic recovery decision is implemented.

## How to run

```powershell
python -m unittest discover -s tests -v
streamlit run app.py
```

The dashboard initializes its SQLite database automatically and creates explicit local demo identities. It does not seed fictional potential matches.

## Future Sprint 5 direction

Sprint 5 should focus on secure real authentication, moderated authorized ingestion, production-grade evidence protection, review workflows, and integration design—not automatic identification or recovery claims.
