# Future Deployment Architecture

```text
Browser → HTTPS reverse proxy → application/service layer → authenticated database
                                      ├→ controlled evidence storage
                                      ├→ isolated AI worker
                                      └→ approved notification provider
```

The current Streamlit + SQLite design is for local demonstration/research. Production would need HTTPS, MFA/SSO, server-side sessions, managed backups, encryption, least-privilege storage, malware scanning, monitoring, incident response, legal/privacy review, operational approvals, and professional security testing. No cloud deployment is performed by this project.

Sprint 9 supplies an example reverse-proxy configuration under `deployment/`, an environment-mode check, a health check, and staging checklist. TLS termination, HSTS, firewalling, trusted proxy configuration, secret injection, and secure backup storage remain deployment-team responsibilities and have not been runtime-tested here.
