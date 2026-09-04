"""Role-safe in-app notification centre; no delivery logic belongs in this UI."""

from __future__ import annotations

import json

from dashboard.components import show_error, status_badge


def render_notifications(st, store, user) -> None:
    st.header("Notifications")
    st.caption("Local in-app notifications only. A potential match remains PENDING until authorized human review.")
    try:
        notifications = store.list_notifications(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return
    if not notifications:
        st.info("No authorized notifications are available.")
        return
    for notification in notifications:
        with st.expander(f"{notification['title']} — {notification['created_at']}"):
            status_badge(st, notification["status"])
            st.write(notification["message"])
            st.caption(f"Case: {notification['case_id']} · Channel: {notification['channel']} · Priority: {notification['priority']}")
            if user["role"] != "PARENT":
                try:
                    metadata = json.loads(notification["metadata_json"])
                    st.caption(f"Authorized stations: {', '.join(metadata.get('stations', [])) or 'None'}")
                except (TypeError, json.JSONDecodeError):
                    pass
            if notification["status"] not in {"READ", "FAILED", "CANCELLED"} and st.button("Mark as read", key=f"notification-read-{notification['id']}"):
                try:
                    store.mark_notification_read(user["username"], notification["id"])
                    st.rerun()
                except Exception as exc:
                    show_error(st, exc)
