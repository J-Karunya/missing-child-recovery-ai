"""Development-only demo account setup helper.

This page is ONLY shown when APP_ENV=DEVELOPMENT (the default).
It allows creating clearly-labelled demo accounts so the demonstrator
does not need to manually run Python scripts.

Security constraints:
  - Never shown in STAGING or PRODUCTION mode.
  - Passwords sourced only from DEMO_SETUP_PASSWORD env var.
  - Passwords are never printed, logged, or displayed in the UI.
  - Demo accounts are created with clearly labelled names.
  - No credentials are committed to version control.
  - Setup is idempotent — running twice does not fail.
"""

from __future__ import annotations

import os

from dashboard.components import show_error


DEMO_USERNAMES = {
    "PARENT": "parent_demo",
    "POLICE": "police_demo",
    "REVIEWER": "reviewer_demo",
    "ADMIN": "admin_demo",
}

DEMO_STATIONS = {
    "POLICE": "DEMO_HQ",
    "ADMIN": "HQ",
}


def render_demo_setup(st, store, user) -> None:
    """Render the development-only demo setup helper."""
    from services.config import ENVIRONMENT_MODE  # noqa: PLC0415

    if ENVIRONMENT_MODE != "DEVELOPMENT":
        st.error(
            "Demo Setup is only available in DEVELOPMENT mode. "
            f"Current mode: {ENVIRONMENT_MODE}"
        )
        return

    st.header("🛠️ Development Demo Setup")
    st.warning(
        "**DEVELOPMENT USE ONLY — NOT FOR PRODUCTION**\n\n"
        "This page creates clearly-labelled demo accounts for demonstration purposes. "
        "It is not shown in STAGING or PRODUCTION mode. "
        "Do not use demo accounts with real case data."
    )

    _render_password_status(st)
    st.divider()
    _render_account_status(st, store)
    st.divider()
    _render_create_accounts(st, store, user)
    st.divider()
    _render_demo_instructions(st)


def _render_password_status(st) -> None:
    password = os.getenv("DEMO_SETUP_PASSWORD", "").strip()
    if not password:
        st.error(
            "DEMO_SETUP_PASSWORD environment variable is not set. "
            "Add it to your `.env` file (not committed to git) and restart the app. "
            "Example: `DEMO_SETUP_PASSWORD=YourDemoPassword123`"
        )
    else:
        st.success(
            "DEMO_SETUP_PASSWORD is configured. "
            "The password is not displayed here."
        )


def _render_account_status(st, store) -> None:
    st.subheader("Demo Account Status")
    cols = st.columns(4)
    for col, (role, username) in zip(cols, DEMO_USERNAMES.items()):
        existing = store.get_user(username)
        if existing:
            if existing.get("password_hash"):
                col.success(f"✅ {role}\n`{username}`")
            else:
                col.warning(f"⚠️ {role}\n`{username}` — password not initialized")
        else:
            col.info(f"⬜ {role}\n`{username}` — not yet created")


def _render_create_accounts(st, store, user) -> None:
    st.subheader("Create Demo Accounts")
    password = os.getenv("DEMO_SETUP_PASSWORD", "").strip()
    if not password:
        st.warning("Set DEMO_SETUP_PASSWORD in your .env file first.")
        return

    if st.button("🔧 Create / Verify All Demo Accounts", type="primary"):
        results: list[str] = []
        errors: list[str] = []

        for role, username in DEMO_USERNAMES.items():
            existing = store.get_user(username)
            if existing:
                if existing.get("password_hash"):
                    results.append(f"✅ {role} ({username}): existing credential preserved")
                    continue
                try:
                    store.admin_reset_password(
                        user["username"], username, password,
                        "initialize passwordless development demo account",
                    )
                    results.append(f"✅ {role} ({username}): password initialized")
                except Exception as exc:
                    errors.append(f"❌ {role} ({username}): {exc}")
                continue
            try:
                station = DEMO_STATIONS.get(role)
                email = f"{username}@demo.local"
                store.create_user(
                    username=username,
                    role=role,
                    station=station,
                    password=password,
                    email=email,
                    actor=user["username"],  # audited under admin actor
                )
                results.append(f"✅ {role} ({username}): created")
            except Exception as exc:
                errors.append(f"❌ {role} ({username}): {exc}")

        for msg in results:
            st.write(msg)
        for msg in errors:
            st.error(msg)

        if not errors:
            st.success(
                "Demo accounts are ready. "
                "Log in with each role to demonstrate the full workflow. "
                "Use the password from DEMO_SETUP_PASSWORD (not shown here)."
            )
        st.rerun()


def _render_demo_instructions(st) -> None:
    st.subheader("How to Demonstrate the Project")
    st.info(
        "Use the username from each role below with the `DEMO_SETUP_PASSWORD` you set."
    )

    steps = """
### Step-by-Step Demo Flow

**1. Login as `parent_demo` (PARENT role)**
- Go to **Cases** → expand **Register Missing Child Case**
- Fill in: Report ID (e.g. `CASE001`), Child ID (e.g. `MC001`), child's name, age, description, last seen location
- Upload a child photograph (JPG/PNG, max 10MB)
- Click **Submit report** → status becomes `PENDING_POLICE_VERIFICATION`
- Go to **Cases** → expand **Upload Recent Parent/Guardian Reference Photo**
- Select the case, upload a recent parent photo

**2. Logout → Login as `police_demo` (POLICE role)**
- Go to **Police Dashboard** → **Pending Complaints** tab
- Find the submitted complaint, review the details
- Fill in complaint number, date, station → click **Verify and Activate Case**
- Case status changes to `ACTIVE`
- Go to **CCTV Analysis** tab → upload a CCTV video for the ACTIVE case
- Scroll to **Stored Footage Ready for Analysis** → click **🤖 Run AI Analysis**
- Watch the live progress: YOLO → DeepSORT → InsightFace → evidence aggregation
- View potential match count (PENDING status — no AI confirmation of child found)

**3. Logout → Login as `reviewer_demo` (REVIEWER role)**
- Go to **Potential Matches** → review PENDING matches
- Click on a match → view evidence, scores, attribute matching
- Click **VERIFY** or **REJECT** with confirmation checkbox

**4. Logout → Login as `parent_demo` again (PARENT role)**
- Go to **Notifications** → see the parent-safe notification (no scores, no CCTV details)
- Go to **Cases** → see safe case status update

**5. Logout → Login as `admin_demo` (ADMIN role)**
- Go to **Admin Overview** → see system-wide audit logs, user list, case lifecycle, evidence status
- Go to **Audit Logs** → see every action that was audited

---
**Key points for the demo audience:**
- AI never says the child is found — only generates `PENDING` potential matches
- Every action is audited
- Parents see only safe, restricted information
- Police evidence and scores are never shown to parents
- The VERIFY/REJECT decision belongs to an authorized human reviewer
"""
    st.markdown(steps)
