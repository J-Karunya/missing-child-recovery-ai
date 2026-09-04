# Sprint 7 — Security, Governance, Lifecycle, and Deployment Readiness

Sprint 7 strengthens the local research prototype without changing YOLO, DeepSORT, InsightFace, cosine similarity, thresholds, attributes, temporal aggregation, or PENDING-only AI semantics.

It adds an audited case lifecycle stored separately from legacy `case_status` for migration compatibility, Argon2 password changes and documented administrator-assisted resets, logical evidence deletion with explicit admin confirmation, MFA-ready service boundaries, safe configuration checks, local database backups, and a static security-check script.

MFA is not faked: `MFAService` reports that no provider is configured and refuses verification. The default notification provider remains local/database-only. Retention remains dry-run first; policy periods are organization and law dependent.

The flow remains: reference photo → embedding → authorized CCTV → YOLO → DeepSORT → InsightFace → explainable temporal evidence → PENDING → SQLite → human VERIFY/REJECT → authorized notifications. AI never declares a child found.
