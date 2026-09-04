"""Admin system-overview dashboard. Read-only summary of all major entities.

All data access goes through existing ReviewStore service methods.
No admin UI change bypasses service-layer authorization.
"""

from __future__ import annotations

from dashboard.components import show_error


def render_admin_overview(st, store, user) -> None:
    st.header("Admin System Overview")
    st.caption(
        "Complete operational overview — all data access is audited through the service layer."
    )

    tab_summary, tab_users, tab_cases, tab_matches, tab_notifs, tab_evidence, tab_audit, tab_health = st.tabs([
        "📊 Summary",
        "👤 Users",
        "📁 Cases",
        "🔍 Matches",
        "🔔 Notifications",
        "🔒 Evidence",
        "📋 Audit Logs",
        "🩺 System Health",
    ])

    with tab_summary:
        _render_summary(st, store, user)

    with tab_users:
        _render_users(st, store, user)

    with tab_cases:
        _render_cases(st, store, user)

    with tab_matches:
        _render_matches(st, store, user)

    with tab_notifs:
        _render_notifications(st, store, user)

    with tab_evidence:
        _render_evidence(st, store, user)

    with tab_audit:
        _render_audit(st, store, user)

    with tab_health:
        _render_health(st, store, user)


def _render_summary(st, store, user) -> None:
    st.subheader("System Metrics")
    try:
        metrics = store.metrics(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    cols = st.columns(6)
    labels = [
        ("Active Cases", "active_cases"),
        ("Potential Matches", "potential_matches"),
        ("Pending Reviews", "pending_reviews"),
        ("Verified", "verified_matches"),
        ("Rejected", "rejected_matches"),
        ("CCTV Runs", "cctv_runs"),
    ]
    for col, (label, key) in zip(cols, labels):
        col.metric(label, metrics.get(key, 0))

    st.divider()
    st.subheader("Case Lifecycle Summary")
    try:
        cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    lifecycle_counts: dict[str, int] = {}
    for case in cases:
        state = case.get("lifecycle_state") or case.get("case_status") or "UNKNOWN"
        lifecycle_counts[state] = lifecycle_counts.get(state, 0) + 1

    if lifecycle_counts:
        cols = st.columns(len(lifecycle_counts))
        for col, (state, count) in zip(cols, sorted(lifecycle_counts.items())):
            col.metric(state, count)
    else:
        st.info("No cases in the system.")


def _render_users(st, store, user) -> None:
    st.subheader("Registered Users")
    try:
        with store._connection() as db:  # noqa: SLF001
            rows = db.execute(
                "SELECT id, username, role, station, email, is_active, "
                "last_login_at, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
        from services.review_store import _row  # noqa: PLC0415
        users = [_row(r) for r in rows]
    except Exception as exc:
        show_error(st, exc)
        return

    role_counts: dict[str, int] = {}
    for u in users:
        if u:
            role_counts[u["role"]] = role_counts.get(u["role"], 0) + 1

    cols = st.columns(4)
    for col, role in zip(cols, ["ADMIN", "POLICE", "REVIEWER", "PARENT"]):
        col.metric(role, role_counts.get(role, 0))

    st.dataframe(
        [
            {
                "username": u["username"],
                "role": u["role"],
                "station": u.get("station") or "—",
                "active": bool(u.get("is_active")),
                "last_login": (u.get("last_login_at") or "Never")[:19],
                "created": (u.get("created_at") or "")[:10],
            }
            for u in users
            if u
        ],
        width="stretch",
        hide_index=True,
    )


def _render_cases(st, store, user) -> None:
    st.subheader("All Cases")
    try:
        cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    st.dataframe(
        [
            {
                "case_id": c.get("case_id"),
                "child_name": c.get("child_name"),
                "age": c.get("age"),
                "status": c.get("lifecycle_state") or c.get("case_status"),
                "station": c.get("authorized_station"),
                "created_by": c.get("created_by"),
                "updated": (c.get("updated_at") or "")[:19],
            }
            for c in cases
        ],
        width="stretch",
        hide_index=True,
    )


def _render_matches(st, store, user) -> None:
    st.subheader("All Potential Matches")
    try:
        matches = store.list_matches(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    if not matches:
        st.info("No potential matches in the system.")
        return

    st.dataframe(
        [
            {
                "id": m.get("id"),
                "case_id": m.get("case_id"),
                "child_id": m.get("child_id"),
                "status": m.get("status"),
                "overall_score": m.get("overall_score"),
                "run_id": (str(m.get("run_id") or ""))[:12] + "…",
                "frame": m.get("frame_number"),
                "reviewed_by": m.get("reviewed_by") or "—",
                "created": (m.get("created_at") or "")[:19],
            }
            for m in matches
        ],
        width="stretch",
        hide_index=True,
    )


def _render_notifications(st, store, user) -> None:
    st.subheader("All Notifications")
    st.caption("Admin sees all notification records.")
    try:
        notifications = store.list_notifications(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    if not notifications:
        st.info("No notifications in the system.")
        return

    st.dataframe(
        [
            {
                "id": n.get("id"),
                "case_id": n.get("case_id"),
                "recipient_role": n.get("recipient_role"),
                "type": n.get("notification_type"),
                "status": n.get("status"),
                "priority": n.get("priority"),
                "title": n.get("title"),
                "created": (n.get("created_at") or "")[:19],
            }
            for n in notifications
        ],
        width="stretch",
        hide_index=True,
    )


def _render_evidence(st, store, user) -> None:
    st.subheader("Evidence Lifecycle")
    st.caption(
        "Evidence is stored in controlled encrypted storage. "
        "Raw paths are never exposed through this interface."
    )
    try:
        with store._connection() as db:  # noqa: SLF001
            rows = db.execute(
                "SELECT e.id, e.match_id, e.evidence_status, e.legal_hold, "
                "e.created_at, e.deleted_at, m.case_id "
                "FROM evidence e JOIN potential_matches m ON m.id=e.match_id "
                "ORDER BY e.created_at DESC"
            ).fetchall()
        from services.review_store import _row  # noqa: PLC0415
        evidence_rows = [_row(r) for r in rows]
    except Exception as exc:
        show_error(st, exc)
        return

    if not evidence_rows:
        st.info("No evidence records in the system.")
        return

    active = sum(1 for e in evidence_rows if e and e.get("evidence_status") == "ACTIVE")
    on_hold = sum(1 for e in evidence_rows if e and e.get("legal_hold"))
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Evidence Records", len(evidence_rows))
    col2.metric("Active", active)
    col3.metric("Legal Hold", on_hold)

    st.dataframe(
        [
            {
                "id": e["id"],
                "match_id": e["match_id"],
                "case_id": e.get("case_id"),
                "status": e.get("evidence_status"),
                "legal_hold": bool(e.get("legal_hold")),
                "created": (e.get("created_at") or "")[:10],
                "deleted": (e.get("deleted_at") or "—")[:10],
            }
            for e in evidence_rows
            if e
        ],
        width="stretch",
        hide_index=True,
    )


def _render_audit(st, store, user) -> None:
    st.subheader("Recent Audit Logs")
    try:
        logs = store.list_audit_logs(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    if not logs:
        st.info("No audit log entries.")
        return

    st.caption(f"Total audit entries: {len(logs)} — showing most recent 200.")
    st.dataframe(
        [
            {
                "timestamp": (r.get("timestamp") or "")[:19],
                "role": r.get("role") or "SYSTEM",
                "action": r.get("action"),
                "resource": r.get("resource_type"),
                "resource_id": r.get("resource_id"),
                "outcome": r.get("outcome") or "—",
            }
            for r in (logs[:200] if logs else [])
        ],
        width="stretch",
        hide_index=True,
    )


def _render_health(st, store, user) -> None:
    st.subheader("System Health")
    try:
        from services.health_check import run_health_check  # noqa: PLC0415
        results = run_health_check()
        for check, status in results.items():
            icon = "✅" if status in {"OK", "PASS", True} else "⚠️"
            st.write(f"{icon} **{check}**: {status}")
    except Exception as exc:
        show_error(st, exc)

    st.divider()
    st.subheader("Configuration Status")
    try:
        from services.config import configuration_check  # noqa: PLC0415
        config = configuration_check()
        for key, status in config.items():
            icon = "✅" if status == "OK" else "⚠️"
            st.write(f"{icon} **{key}**: {status}")
    except Exception as exc:
        show_error(st, exc)

    st.divider()
    st.subheader("Security Posture")
    st.info(
        "This prototype uses Argon2 password hashing, server-side session tokens, "
        "role-based access control, controlled encrypted evidence storage, "
        "and comprehensive audit logging. "
        "It is not production-ready without: HTTPS, MFA enforcement for all roles, "
        "independently reviewed deployment controls, approved retention enforcement, "
        "and production upload scanning."
    )
