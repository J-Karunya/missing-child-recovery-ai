"""Explicit development-only user initializer for local dashboard demonstrations.

Set DEMO_USER_PASSWORD in the environment before running. This script does not
print passwords, and it is never called automatically by the application.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.review_store import ReviewStore


def main() -> None:
    password = os.getenv("DEMO_USER_PASSWORD", "")
    admin_username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.test")
    if len(password) < 12:
        raise SystemExit("Set DEMO_USER_PASSWORD to a development-only password of at least 12 characters.")
    store = ReviewStore()
    store.initialize()
    admin = store.bootstrap_admin(admin_username, admin_email, password)
    users = (("police_demo", "POLICE", "HQ"), ("reviewer_demo", "REVIEWER", "HQ"), ("parent_demo", "PARENT", None))
    for username, role, station in users:
        if not store.get_user(username):
            store.create_user(username, role, station=station, password=password, email=f"{username}@example.test", actor=admin["username"])
    print("Development demo accounts are ready. Passwords were not printed.")


if __name__ == "__main__":
    main()
