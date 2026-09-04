# Sprint 8 — Production-Oriented Security Boundaries

Sprint 8 hardens the local research prototype without changing its AI pipeline. `mfa_service.py` uses maintained `pyotp` TOTP verification and Fernet-encrypts stored secrets when an environment-managed key is supplied. MFA is optional by policy; an enabled account cannot silently bypass it.

`session_service.py` stores only a SHA-256 hash of a cryptographically random session token in SQLite. It supports expiry, revocation, and active-account rechecks. SQLite is suitable for this single-instance prototype, not multi-instance production.

`evidence_crypto.py` uses Fernet authenticated encryption. Keys are never hard-coded, logged, placed in Streamlit state, or stored in database records. Decryption is after service authorization; parents are denied. `upload_scanner.py` fails closed: unavailable scanning leaves content non-processable.

Evidence can be put under admin-controlled legal hold; held evidence cannot be logically deleted. This is not production-ready: keys need managed secret storage, uploads need an approved malware scanner, and deployment needs HTTPS, MFA policy, hardened infrastructure, and governance.
