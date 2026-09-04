"""Conservative retention reports for local prototype evidence and records.

The default path is dry-run. Deletion requires an explicit caller choice and
should be used only under applicable law and authorized evidence policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .config import AUDIT_RETENTION_DAYS, CCTV_RETENTION_DAYS, EVIDENCE_RETENTION_DAYS, RETENTION_DRY_RUN
    from .review_store import AuthorizationError, ReviewStore
except ImportError:
    from config import AUDIT_RETENTION_DAYS, CCTV_RETENTION_DAYS, EVIDENCE_RETENTION_DAYS, RETENTION_DRY_RUN
    from review_store import AuthorizationError, ReviewStore


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class RetentionService:
    def __init__(self, store: ReviewStore) -> None:
        self.store = store

    def report(self, actor: str) -> dict[str, Any]:
        """List eligible records only; this never removes evidence."""
        self.store._require(actor, "manage_users")
        with self.store._connection() as db:
            evidence = [dict(row) for row in db.execute("SELECT e.* FROM evidence e WHERE e.created_at < ?", (_cutoff(EVIDENCE_RETENTION_DAYS),))]
            submissions = [dict(row) for row in db.execute("SELECT * FROM cctv_submissions WHERE created_at < ?", (_cutoff(CCTV_RETENTION_DAYS),))]
            audits = [dict(row) for row in db.execute("SELECT id, timestamp, action, resource_type, resource_id FROM audit_logs WHERE timestamp < ?", (_cutoff(AUDIT_RETENTION_DAYS),))]
        return {"dry_run": RETENTION_DRY_RUN, "expired_evidence": evidence, "expired_submissions": submissions, "expired_audit_logs": audits}

    def apply(self, actor: str, explicitly_enabled: bool = False) -> dict[str, int]:
        """Delete only after an explicit non-dry-run decision by an administrator."""
        administrator = self.store._require(actor, "manage_users")
        report = self.report(actor)
        if RETENTION_DRY_RUN or not explicitly_enabled:
            return {"deleted_evidence": 0, "deleted_submissions": 0, "deleted_audit_logs": 0}
        deleted_evidence = deleted_submissions = deleted_audits = 0
        with self.store._connection() as db:
            for item in report["expired_evidence"]:
                for name in (item.get("image_path"), item.get("metadata_path")):
                    self._delete_controlled_file(name)
                db.execute("DELETE FROM evidence WHERE id=?", (item["id"],))
                deleted_evidence += 1
            for item in report["expired_submissions"]:
                self._delete_controlled_file(item.get("stored_name"), directory_name="cctv_uploads")
                db.execute("DELETE FROM cctv_submissions WHERE id=?", (item["id"],))
                deleted_submissions += 1
            for item in report["expired_audit_logs"]:
                db.execute("DELETE FROM audit_logs WHERE id=?", (item["id"],))
                deleted_audits += 1
        self.store._audit(administrator, "RETENTION_APPLIED", "retention", "policy", {"evidence": deleted_evidence, "submissions": deleted_submissions, "audits": deleted_audits})
        return {"deleted_evidence": deleted_evidence, "deleted_submissions": deleted_submissions, "deleted_audit_logs": deleted_audits}

    @staticmethod
    def _delete_controlled_file(name: str | None, directory_name: str = "alerts") -> None:
        if not name:
            return
        try:
            from .config import DATA_DIR
        except ImportError:
            from config import DATA_DIR
        candidate = (DATA_DIR / directory_name / Path(name).name).resolve()
        root = (DATA_DIR / directory_name).resolve()
        if candidate.parent == root and candidate.is_file():
            candidate.unlink()
