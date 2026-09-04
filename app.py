"""Sprint 13 Streamlit dashboard entry point.

Adds role-aware navigation and exposes the existing CCTV pipeline through the UI.
The AI decision chain is unchanged:
  YOLO → DeepSORT → InsightFace → attribute comparison → temporal evidence
  → PENDING → authorized human VERIFY / REJECT

AI never automatically declares a child found.
"""

from __future__ import annotations


# ── Role-specific navigation definitions ──────────────────────────────────────
# Each role sees only the pages appropriate to its responsibilities.
# ADMIN sees everything. Roles are additive — an ADMIN could fill any role.

_PAGES_BY_ROLE: dict[str, list[str]] = {
    "PARENT": [
        "Dashboard",
        "My Cases",
        "Notifications",
        "Profile",
        "About System",
    ],
    "POLICE": [
        "Dashboard",
        "Police Dashboard",
        "Cases",
        "Potential Matches",
        "Notifications",
        "Evidence",
        "Age Progression",
        "Profile",
        "About System",
    ],
    "REVIEWER": [
        "Dashboard",
        "Potential Matches",
        "Evidence",
        "Age Progression",
        "Notifications",
        "Profile",
        "About System",
    ],
    "ADMIN": [
        "Dashboard",
        "Admin Overview",
        "Police Dashboard",
        "Cases",
        "Potential Matches",
        "Evidence",
        "Age Progression",
        "Notifications",
        "Audit Logs",
        "Demo Setup",
        "Profile",
        "About System",
    ],
}


def main() -> None:
    import streamlit as st

    from dashboard.admin_view import render_admin_overview
    from dashboard.age_progression_view import render_age_progression
    from dashboard.audit_view import render_audit
    from dashboard.case_view import render_cases
    from dashboard.components import (
        login_screen,
        logout_button,
        require_authenticated_user,
        show_error,
    )
    from dashboard.demo_setup import render_demo_setup
    from dashboard.match_view import render_evidence, render_matches
    from dashboard.notification_view import render_notifications
    from dashboard.police_view import render_police_dashboard
    from services.config import (
        BOOTSTRAP_ADMIN_EMAIL,
        BOOTSTRAP_ADMIN_PASSWORD,
        BOOTSTRAP_ADMIN_USERNAME,
        ENVIRONMENT_MODE,
    )
    from services.review_store import AuthorizationError, ReviewStore

    st.set_page_config(
        page_title="Missing Child Recovery AI",
        page_icon="🔎",
        layout="wide",
    )

    store = ReviewStore()
    store.initialize()

    # Bootstrap first admin if database is empty
    if store.credentialed_active_user_count() == 0:
        if not (BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD):
            st.error(
                "No administrator exists. "
                "Set BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_EMAIL, and "
                "BOOTSTRAP_ADMIN_PASSWORD as environment variables, then restart the app."
            )
            return
        try:
            store.bootstrap_admin(
                BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD
            )
        except (ValueError, AuthorizationError):
            st.error(
                "Administrator bootstrap could not be completed. "
                "Check the configured values and restart the app."
            )
            return

    user = require_authenticated_user(st, store)
    if not user:
        login_screen(st, store)
        return

    # ── Authenticated UI ───────────────────────────────────────────────────────
    st.title("Missing Child Recovery AI")
    st.caption(
        "Secured prototype. "
        "AI creates **PENDING** potential matches; authorized humans review them."
    )
    st.sidebar.success(f"Signed in as **{user['username']}** ({user['role']})")
    logout_button(st, store, user)

    # ── Role-aware navigation ──────────────────────────────────────────────────
    role = user["role"]
    pages = _PAGES_BY_ROLE.get(role, ["Dashboard", "Profile", "About System"])

    # Only show Demo Setup in DEVELOPMENT mode
    if "Demo Setup" in pages and ENVIRONMENT_MODE != "DEVELOPMENT":
        pages = [p for p in pages if p != "Demo Setup"]

    page = st.sidebar.radio("Navigation", pages)

    # ── Page routing ───────────────────────────────────────────────────────────

    if page == "Dashboard":
        _render_dashboard(st, store, user)

    elif page == "My Cases":
        # Parent-focused case view (same render_cases function, parent role filters apply)
        render_cases(st, store, user)

    elif page == "Cases":
        render_cases(st, store, user)

    elif page == "Police Dashboard":
        render_police_dashboard(st, store, user)

    elif page == "Admin Overview":
        render_admin_overview(st, store, user)

    elif page == "Potential Matches":
        render_matches(st, store, user)

    elif page == "Notifications":
        render_notifications(st, store, user)

    elif page == "Evidence":
        render_evidence(st, store, user)

    elif page == "Age Progression":
        render_age_progression(st, store, user)

    elif page == "Audit Logs":
        render_audit(st, store, user)

    elif page == "Demo Setup":
        render_demo_setup(st, store, user)

    elif page == "Profile":
        _render_profile(st, user)

    else:
        _render_about(st)


def _render_dashboard(st, store, user) -> None:
    """Role-aware dashboard landing page."""
    from dashboard.components import show_error

    role = user["role"]

    if role == "PARENT":
        st.header("My Missing-Child Case Dashboard")
        st.info(
            "Use **My Cases** in the sidebar to submit a report, upload photos, "
            "and track your case status. "
            "Use **Notifications** to see authorized updates."
        )
        try:
            cases = store.list_cases(user["username"])
            st.metric("My cases", len(cases))
            if cases:
                st.subheader("Case status")
                for case in cases:
                    state = case.get("lifecycle_state") or case.get("case_status")
                    safe_status = {
                        "PENDING_POLICE_VERIFICATION": "⏳ Awaiting police verification",
                        "ACTIVE": "🟢 Active — under investigation",
                        "CLOSED": "⚫ Closed",
                    }.get(state, state)
                    st.write(f"**{case['case_id']}** — {case['child_name']}: {safe_status}")
        except Exception as exc:
            show_error(st, exc)

    elif role == "POLICE":
        st.header("Police Operations Dashboard")
        try:
            metrics = store.metrics(user["username"])
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Active cases", metrics.get("active_cases", 0))
            col2.metric("Potential matches", metrics.get("potential_matches", 0))
            col3.metric("Pending reviews", metrics.get("pending_reviews", 0))
            col4.metric("CCTV runs", metrics.get("cctv_runs", 0))

            cases = store.list_cases(user["username"])
            pending = [
                c for c in cases
                if (c.get("lifecycle_state") or c.get("case_status")) == "PENDING_POLICE_VERIFICATION"
            ]
            if pending:
                st.warning(
                    f"**{len(pending)} complaint(s) awaiting police verification.** "
                    "Go to → **Police Dashboard** to verify."
                )
        except Exception as exc:
            show_error(st, exc)

    elif role == "REVIEWER":
        st.header("Reviewer Dashboard")
        try:
            metrics = store.metrics(user["username"])
            col1, col2, col3 = st.columns(3)
            col1.metric("Potential matches", metrics.get("potential_matches", 0))
            col2.metric("Pending your review", metrics.get("pending_reviews", 0))
            col3.metric("Reviewed", metrics.get("verified_matches", 0) + metrics.get("rejected_matches", 0))

            pending_matches = store.list_matches(user["username"])
            pending = [m for m in pending_matches if m.get("status") == "PENDING"]
            if pending:
                st.warning(
                    f"**{len(pending)} potential match(es) await your review.** "
                    "Go to → **Potential Matches**."
                )
        except Exception as exc:
            show_error(st, exc)

    else:  # ADMIN
        st.header("Administrator Dashboard")
        try:
            metrics = store.metrics(user["username"])
            labels = [
                ("Active cases", "active_cases"),
                ("Potential matches", "potential_matches"),
                ("Pending reviews", "pending_reviews"),
                ("Verified", "verified_matches"),
                ("Rejected", "rejected_matches"),
                ("CCTV runs", "cctv_runs"),
            ]
            for column, (label, key) in zip(st.columns(6), labels):
                column.metric(label, metrics.get(key, 0))

            st.subheader("Recent potential matches")
            st.dataframe(
                store.list_matches(user["username"])[:10],
                width="stretch",
                hide_index=True,
            )
        except Exception as exc:
            show_error(st, exc)


def _render_profile(st, user) -> None:
    st.header("Account Profile")
    st.write({
        "username": user["username"],
        "role": user["role"],
        "station": user.get("station"),
        "active": bool(user.get("is_active")),
    })
    st.info(
        "This is a secured prototype. "
        "Production requires MFA, HTTPS, secure cookies, "
        "deployment hardening, and independent security review."
    )


def _render_about(st) -> None:
    st.header("About the System")
    st.markdown("""
### Missing Child Recovery AI — System Overview

The existing AI decision chain remains unchanged:

```
YOLO detection
    ↓
DeepSORT tracking
    ↓
InsightFace face comparison
    ↓
Attribute + temporal evidence aggregation
    ↓
PENDING potential match (AI result — never a final decision)
    ↓
Authorized human REVIEWER: VERIFY or REJECT
```

**AI never automatically declares a child found.**

All potential matches begin as **PENDING** and require explicit human review
before any action is taken. The system is:
- **AI-assisted** — YOLO, DeepSORT, and InsightFace provide evidence
- **Human-verified** — every decision belongs to an authorized reviewer
- **Security-conscious** — Argon2 auth, encrypted evidence, audit logging
- **PENDING-first** — no automatic confirmations, ever

### Sprint History
Sprints 1–12: Core pipeline, case management, auth, notifications, age progression.
Sprint 13: End-to-end demo UI integration — CCTV pipeline accessible from dashboard.
    """)


if __name__ == "__main__":
    main()
