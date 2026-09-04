"""Potential-match review UI, separated from detection and matching services."""

from __future__ import annotations

import json

from dashboard.components import show_error, status_badge


def render_matches(st, store, user) -> None:
    st.header("Potential Matches")
    try:
        matches = store.list_matches(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return
    if not matches:
        st.info("No potential matches are available for this role.")
        return
    for match in matches:
        title = f"Potential Match #{match['id']} — {match['case_id']}"
        with st.expander(title):
            status_badge(st, match["status"])
            if user["role"] == "PARENT":
                st.write("Parent-safe status only. Police evidence and internal scores are restricted.")
                st.write({key: match.get(key) for key in ("case_id", "child_id", "created_at", "status", "reviewed_at")})
                continue
            st.write({key: match.get(key) for key in ("case_id", "child_id", "track_id", "run_id", "video_name", "frame_number", "created_at")})
            cols = st.columns(5)
            for column, label, key in zip(cols, ("Face", "Clothing", "Accessory", "Physical", "Overall"), ("face_score", "clothing_score", "accessory_score", "physical_score", "overall_score")):
                column.metric(label, match.get(key) if match.get(key) is not None else "Unknown")
            _reasons(st, match.get("reason"))
            evidence = store.get_evidence(user["username"], match["id"])
            if evidence:
                st.caption("Evidence is restricted to police/reviewer/admin roles.")
                image_path = store.evidence_display_path(user["username"], match["id"])
                if image_path:
                    st.image(str(image_path), caption="Restricted evidence image")
                elif evidence.get("image_path"):
                    st.warning("Registered evidence image is unavailable in controlled storage.")
            if user["role"] in {"ADMIN", "POLICE", "REVIEWER"}:
                _review_actions(st, store, user, match)


def render_evidence(st, store, user) -> None:
    st.header("Evidence")
    if user["role"] == "PARENT":
        st.info("Evidence images and operational details are restricted to authorized reviewers.")
        return
    st.caption("Evidence is resolved only from the controlled alerts directory; raw filesystem paths are never entered by users.")
    render_matches(st, store, user)


def _reasons(st, text) -> None:
    try:
        reasons = json.loads(text) if text else {}
    except (TypeError, json.JSONDecodeError):
        reasons = {"available": text or "No structured explanation recorded."}
    st.subheader("Matching evidence")
    st.write(reasons.get("matched", []) or "No confirmed supporting attributes.")
    st.subheader("Mismatching evidence")
    st.write(reasons.get("mismatched", []) or "No known mismatches.")
    st.subheader("Unknown information")
    st.write(reasons.get("unknown", []) or "No unknown fields recorded.")


def _review_actions(st, store, user, match) -> None:
    with st.form(f"review-{match['id']}"):
        action = st.selectbox("Review action", ["KEEP_PENDING", "VERIFY", "REJECT"], key=f"action-{match['id']}")
        notes = st.text_area("Review notes", key=f"notes-{match['id']}")
        confirm = st.checkbox("I confirm this is an authorized human review.", key=f"confirm-{match['id']}")
        submitted = st.form_submit_button("Save review decision")
    if submitted:
        try:
            updated = store.review_match(user["username"], match["id"], action, notes, confirmed=confirm)
            st.success(f"Potential Match status is now {updated['status']}.")
            st.rerun()
        except Exception as exc:
            show_error(st, exc)
