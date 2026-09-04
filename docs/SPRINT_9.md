# Sprint 9 — Deployment and Operations Hardening

Sprint 9 places operations controls around the unchanged AI pipeline. Secrets are read from an injectable provider, not source code or SQLite. Production/staging configuration reports only status, never values. Encrypted evidence storage uses Fernet and controlled opaque filenames; a parent cannot decrypt evidence. Scanner availability is fail-closed outside explicitly permitted development configuration.

Backup restoration defaults to dry-run, validates project tables, and requires explicit replacement confirmation. Legal holds remain service-layer/admin controlled and prevent deletion. Health checks report only component status. HTTPS belongs at a reverse-proxy boundary, demonstrated only by example configuration—not a tested deployment.

## Deferred issues

Managed cloud secret providers, a real approved malware scanner, production TLS deployment, multi-instance session storage, and a formal legal-policy workflow require organizational approval and remain outside this local prototype.
