# Current Status

## Completed

Sprints 1–13 IMPLEMENTED. The local pipeline validates a case profile, optionally converts its description into structured `true`/`false`/`null` attributes, creates a normalized InsightFace embedding, detects people with YOLO, tracks them with DeepSORT, compares faces with cosine similarity, aggregates evidence across frames, and creates only `PENDING` potential-match evidence. Sprint 12 adds a parent report → police verification → active-case gate and review-gated parent-assisted age-progression references. Sprint 13 adds a complete end-to-end demo UI with role-aware navigation, a "Run AI Analysis" button that invokes the existing CCTV pipeline from the Streamlit dashboard, and a development demo setup helper.

Sprints 9–10 add secret-provider, production/staging configuration, fail-closed scanner, controlled encrypted evidence storage, restore dry-run, health-check, and reverse-proxy/staging documentation boundaries. Sprint 11 validates 80 unit tests and the local login screen, and connects dashboard login/logout to server-side session tokens with configured-MFA enforcement. Authenticated browser role workflows remain intentionally untested without entering account credentials.

The matcher accepts a configured simple video filename, reports progress, records a run ID, saves evidence image/JSON only for threshold-crossing tracks, and writes structured match and audit logs. Sprint 4 adds SQLite-backed case/match/evidence/audit storage. Sprint 5 adds Argon2 authentication, role-aware sessions, parent isolation, login throttling, secure evidence lookup, controlled uploads, and report-first retention. Sprint 6 adds audited local notification records for authorized parents and staff at original/active assigned stations.

## Working now

Run from the project root:

```powershell
python -m unittest discover -s tests -v
python services/profile_builder.py
python services/generate_embedding.py
python services/detector.py
python services/cctv_matcher.py
streamlit run app.py
```

Without `OPENAI_API_KEY`, profile parsing is intentionally safe: all uncertain attributes become `null`; the rest of the pipeline continues.

## Partially implemented

Visual attributes currently include only a conservative coarse top-colour observation. DAY/NIGHT is only a label, not enhancement. Authentication is suitable for a student prototype but not a replacement for MFA, HTTPS, encryption, secure server-side sessions, or governance. Retention is report-only by default.

## Not implemented

Power BI, live or multi-camera CCTV, cloud deployment, public uploads, production messaging integrations, and production deployment controls are not started. Sprint 12 provides an age-progression provider boundary and review workflow, but no trained provider is bundled and it must not be represented as a guaranteed appearance or genetic prediction. Sprint 6 provides in-app local notifications only, not real SMS/email/push delivery or GPS tracking.

## Known limitations

Scores are prototype evidence, not calibrated probabilities. A zero-match result does not prove absence. Human review is required for every potential match. This project is not production-ready because operational governance, independently assessed deployment controls, approved retention enforcement, production upload scanning, and a validated age-progression provider are not implemented.

## Sprint 6 direction

The next sprint should focus on production hardening such as HTTPS, MFA, encrypted storage/key management, malware scanning, approved retention, configurable approved external notification providers, and independent security/privacy review without replacing the existing detection, tracking, face-comparison, or PENDING-review pipeline.
