"""CLI wrapper for the existing report-first retention service."""
from __future__ import annotations
import json, sys
from services.retention import RetentionService
from services.review_store import ReviewStore

if __name__ == "__main__":
    store = ReviewStore(); store.initialize()
    # An administrator identity is intentionally required; this utility does not bypass RBAC.
    actor = "admin"
    try:
        print(json.dumps(RetentionService(store).report(actor), default=str, indent=2))
    except Exception:
        print("Retention report requires an authenticated administrator context.")
        sys.exit(1)
