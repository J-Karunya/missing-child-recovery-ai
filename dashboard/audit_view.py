"""Restricted audit-log presentation."""

from __future__ import annotations

from dashboard.components import show_error


def render_audit(st, store, user) -> None:
    st.header("Audit Logs")
    try:
        rows = store.list_audit_logs(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return
    st.dataframe(rows, width="stretch", hide_index=True)
