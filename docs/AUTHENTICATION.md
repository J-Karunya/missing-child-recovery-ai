# Authentication and Authorization

## What Sprint 5 adds

The dashboard no longer lets a visitor pick a demo identity. A user signs in with a username/email and password. `services/auth.py` hashes passwords with Argon2; only the hash is stored in SQLite. Plaintext passwords are never stored in database fields, audit records, Streamlit session state, or error messages.

`services/review_store.py` verifies credentials, checks active/inactive state, records failed attempts, applies a temporary configurable lockout, and emits minimal login/logout audit events. Login always gives the same message—`Invalid credentials.`—so the UI does not reveal whether an account exists.

## First administrator

Before first launch, set these environment variables in the terminal that starts Streamlit:

```powershell
$env:BOOTSTRAP_ADMIN_USERNAME="admin"
$env:BOOTSTRAP_ADMIN_EMAIL="admin@example.org"
$env:BOOTSTRAP_ADMIN_PASSWORD="choose-a-unique-password-of-at-least-12-characters"
streamlit run app.py
```

The password shown is an example only. Do not place a real password in source code, `.env.example`, documentation, tests, or version control.

For a development-only role demonstration, an explicit script can create police, reviewer, and parent demo accounts after the first admin is available:

```powershell
$env:DEMO_USER_PASSWORD="development-only-password-with-12-or-more-characters"
python scripts/create_demo_users.py
```

The script never runs automatically and never prints a password. Do not use demo accounts or a shared development password in a real deployment.

## Session behavior

After successful login, Streamlit session state contains only user ID, username, role, issue time, and last activity time—never a password or token. Every dashboard rerun checks that the session has not expired and that the database account is still active. Signing out clears session state and writes a logout audit event.

## Authorization matrix

| Role | Allowed data/actions |
|---|---|
| ADMIN | User administration, all cases/matches/evidence, audits, stations/cameras, and reviews. |
| POLICE | Assigned-station cases, operational matches/evidence, review actions, and controlled CCTV submission. |
| REVIEWER | Authorized/station potential matches, evidence inspection, KEEP PENDING/VERIFY/REJECT. |
| PARENT | Only linked case and parent-safe match status. No evidence, scores, source video, reviewer notes, submissions, or audit logs. |

The same checks run inside the service/repository layer, not merely in hidden dashboard controls.

## Production boundary

This is a secured prototype, not production authentication. A deployment still needs HTTPS, secure reverse-proxy configuration, secure cookies where applicable, MFA, password-reset controls, account recovery, server-side session storage, rate limiting at the network edge, monitoring, and security testing.
