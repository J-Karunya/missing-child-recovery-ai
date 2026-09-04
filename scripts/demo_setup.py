"""Explicit development-only demo-account preparation.

Run with ``python scripts/demo_setup.py --apply`` after setting
``DEMO_SETUP_PASSWORD``. Existing passwords are never replaced; only missing
demo accounts and existing passwordless demo accounts are initialized.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Support the documented `python scripts/demo_setup.py --apply` command from
# the project root without requiring callers to set PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.config import ENVIRONMENT_MODE
from services.review_store import ReviewStore, ValidationError

DEMO_USERS = (
    ("parent_demo", "PARENT", None),
    ("police_demo", "POLICE", "DEMO_HQ"),
    ("reviewer_demo", "REVIEWER", None),
    ("admin_demo", "ADMIN", "HQ"),
)


def prepare_demo_accounts(apply: bool = False) -> list[str]:
    if ENVIRONMENT_MODE != "DEVELOPMENT":
        raise ValidationError("Demo setup is available only in DEVELOPMENT mode.")
    password = os.getenv("DEMO_SETUP_PASSWORD", "")
    if len(password) < 12:
        raise ValidationError("Set DEMO_SETUP_PASSWORD to a unique password of at least 12 characters.")
    store = ReviewStore()
    store.initialize()
    admin = store.get_user("admin")
    if not admin or not admin.get("password_hash"):
        raise ValidationError("Sign in as an existing local admin before preparing demo accounts.")
    result: list[str] = []
    for username, role, station in DEMO_USERS:
        existing = store.get_user(username)
        if existing and existing.get("password_hash"):
            result.append(f"{username}: existing credential preserved")
        elif existing:
            result.append(f"{username}: passwordless account will be initialized" if not apply else f"{username}: password initialized")
            if apply:
                store.admin_reset_password("admin", username, password, "initialize passwordless development demo account")
        else:
            result.append(f"{username}: will be created" if not apply else f"{username}: created")
            if apply:
                store.create_user(username, role, station=station, password=password, email=f"{username}@demo.local", actor="admin")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare development-only demo accounts without overwriting credentials.")
    parser.add_argument("--apply", action="store_true", help="Create missing demo accounts and initialize passwordless demo accounts.")
    args = parser.parse_args()
    for line in prepare_demo_accounts(args.apply):
        print(line)
    print("Applied." if args.apply else "Dry run only. Re-run with --apply to make changes.")


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, ValueError) as exc:
        print(f"Demo setup unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2)
