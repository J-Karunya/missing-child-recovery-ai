# Threat Model

This is a security-conscious research prototype, not a certified law-enforcement platform.

| Threat | Impact | Current mitigation | Remaining limitation |
|---|---|---|---|
| Unauthorized parent/police access | Private-case disclosure | Role, case, and station checks; parent-safe views | Local deployment lacks enterprise identity controls. |
| Stolen or compromised account | Unauthorized actions | Argon2, lockout, active checks, short sessions, MFA-ready boundary | No configured MFA or server-side session store. |
| Malicious CCTV/reference upload | Code/data exposure or DoS | Allowlists, size limits, controlled names/paths, basic signature validation | No malware scanner or sandbox. |
| Database tampering | History/evidence loss | Foreign keys, transactions, append-only application audit, backups | SQLite file requires OS/infrastructure protection. |
| Evidence/notification leakage | Sensitive investigation disclosure | RBAC, controlled evidence IDs, parent-safe templates | No encryption at rest or external delivery protection. |
| Session theft | Account takeover | Timeout, logout, active-user recheck | Streamlit local sessions are not production session infrastructure. |
| Path traversal / SQL injection | File/database compromise | Safe filenames and parameterized values | Static checks are not a full penetration test. |
| Incorrect AI match | Harmful decision | Multi-frame evidence, PENDING and authorized review | Scores are not proof or calibrated probabilities. |
| Insider misuse | Authorized misuse | Audits, station scope, minimum data | Requires organizational oversight and review. |
