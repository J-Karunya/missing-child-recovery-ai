# Sprint 5 — Security, Authentication, Privacy, and Secure Evidence Access

## Objective

Sprint 5 hardens the existing local review prototype. It preserves the core AI pipeline and PENDING semantics while adding real local authentication, session handling, centralized authorization, retention reporting, safer evidence/upload boundaries, and security-focused tests.

## Features implemented

- Argon2 password hashing and verification.
- Username/email login, active-account checks, generic failures, configurable lockout, and login/logout auditing.
- Streamlit session state with user ID, expiry, logout, and revalidation of active account status.
- Central role permissions and service-layer user/case/evidence checks.
- Parent-safe data isolation enforced by repository methods, not only hidden UI controls.
- Terminal review decisions: only PENDING matches can be KEEP PENDING, VERIFIED, or REJECTED. AI cannot set VERIFIED.
- Parameterized SQLite statements, foreign keys, migration of Sprint 4 user/audit fields, and explicit transaction behavior.
- Safe migration for existing Sprint 4 user databases: a legacy user can receive the first Argon2 admin credential only when no credentialed active account exists.
- Audit records for AI-created PENDING matches as well as login, logout, review, evidence, upload, and administrative actions.
- Basic MP4/AVI/MOV content-signature checks, generated upload names, encoded-traversal rejection, and controlled evidence resolution.
- Report-first data-retention service with dry-run enabled by default.

## What is not implemented

This is not production ready. It does not provide MFA, password resets, HTTPS, secure server-side session storage, malware scanning, legal-hold controls, encryption at rest, cloud deployment, notifications, live CCTV, GPS/live location, age progression, or automatic recovery declarations.

## Run

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
streamlit run app.py
```

Set the required bootstrap-admin environment variables described in [AUTHENTICATION.md](AUTHENTICATION.md) before the first dashboard launch.

## Future Sprint 6 direction

Sprint 6 should focus on deployment safety: HTTPS/reverse proxy, MFA, reset/recovery workflows, encryption and key management, malware scanning, operational policy, legal/privacy review, and independent security testing. It must not weaken the principle that AI produces evidence while humans make verification decisions.
