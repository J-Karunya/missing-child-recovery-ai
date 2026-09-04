# Privacy and Retention

## Data minimization

The system processes only authorized case information, reference images, CCTV footage, generated evidence, and necessary review metadata. It does not place raw face embeddings, passwords, API keys, or access tokens into dashboard tables or audit details.

Parent-safe output is intentionally narrower than police/reviewer output. Parents cannot access CCTV sources, frames, score breakdowns, internal notes, reviewer identities, evidence metadata, or audit history.

## Retention framework

Configuration variables:

- `EVIDENCE_RETENTION_DAYS`
- `CCTV_RETENTION_DAYS`
- `AUDIT_RETENTION_DAYS`
- `RETENTION_DRY_RUN=true`

`services/retention.py` first produces a report of potentially expired evidence, CCTV submissions, and audit records. Dry-run is the default and removes nothing. Actual removal needs both `RETENTION_DRY_RUN=false` and an explicit administrator action in code.

Do not use automatic deletion for real investigative material until applicable law, police procedure, legal holds, organizational policy, chain-of-custody requirements, and human approval have been reviewed. This project makes no claim of legal compliance.

## Evidence and uploads

Evidence is requested by database ID, authorized against the associated case, and resolved only from controlled project folders. CCTV uploads receive generated server-side filenames, accept only MP4/AVI/MOV after basic content-signature checks, and start as `PENDING_PROCESSING`. Uploaded files are not executed or automatically processed.
