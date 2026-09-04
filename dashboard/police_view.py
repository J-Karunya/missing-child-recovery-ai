"""Police-specific dashboard: pending complaints, verification, and CCTV AI analysis.

This module only calls ReviewStore service methods and the pipeline_service
orchestration wrapper. It does not contain AI logic.
"""

from __future__ import annotations

from dashboard.components import show_error, status_badge


def render_police_dashboard(st, store, user) -> None:
    """Full police workflow: complaints → verify → upload CCTV → run analysis."""
    st.header("Police Dashboard")

    tab_complaints, tab_cctv, tab_matches = st.tabs([
        "📋 Pending Complaints",
        "📹 CCTV Analysis",
        "🔍 Potential Matches",
    ])

    with tab_complaints:
        _render_pending_complaints(st, store, user)

    with tab_cctv:
        _render_cctv_analysis(st, store, user)

    with tab_matches:
        _render_police_matches(st, store, user)


# ── Pending Complaints ─────────────────────────────────────────────────────────

def _render_pending_complaints(st, store, user) -> None:
    st.subheader("Pending Police Complaints")
    st.caption(
        "These reports have been submitted by parents and await police verification "
        "before CCTV processing can begin."
    )
    try:
        all_cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    pending = [
        c for c in all_cases
        if (c.get("lifecycle_state") or c.get("case_status")) == "PENDING_POLICE_VERIFICATION"
    ]
    active = [
        c for c in all_cases
        if (c.get("lifecycle_state") or c.get("case_status")) == "ACTIVE"
    ]

    col1, col2, col3 = st.columns(3)
    col1.metric("Pending Verification", len(pending))
    col2.metric("Active Cases", len(active))
    col3.metric("Total Cases", len(all_cases))

    if not pending:
        st.info("No complaints are currently awaiting verification.")
    else:
        for case in pending:
            with st.expander(
                f"🟠 {case['case_id']} — {case['child_name']} "
                f"(submitted {case.get('created_at', '')[:10]})"
            ):
                _render_complaint_detail(st, store, user, case)

    st.divider()
    st.subheader("Active Cases")
    if not active:
        st.info("No active cases.")
    else:
        for case in active:
            with st.expander(
                f"🟢 {case['case_id']} — {case['child_name']}"
            ):
                st.write({
                    k: case.get(k)
                    for k in ("case_id", "child_id", "child_name", "age",
                              "authorized_station", "lifecycle_state", "updated_at")
                })
                _render_station_section(st, store, user, case)


def _render_complaint_detail(st, store, user, case) -> None:
    status_badge(st, case.get("lifecycle_state") or case["case_status"])
    cols = st.columns(2)
    cols[0].write({
        "Case ID": case.get("case_id"),
        "Child": case.get("child_name"),
        "Age": case.get("age"),
        "Last seen": case.get("last_seen_location") or "Not recorded",
        "Station": case.get("authorized_station"),
    })
    cols[1].write({
        "Complaint #": case.get("police_complaint_number") or "—",
        "Complaint date": case.get("police_complaint_date") or "—",
        "Complaint station": case.get("complaint_police_station") or "—",
        "Submitted": case.get("created_at", "")[:19],
    })
    try:
        refs = store.list_parent_references(user["username"], case["case_id"])
        st.caption(
            f"Parent/guardian reference photos: {len(refs)} uploaded"
            if refs
            else "No parent/guardian reference photos uploaded yet."
        )
    except Exception:
        pass

    st.subheader("Verify Complaint")
    with st.form(f"police-verify-{case['case_id']}"):
        number = st.text_input(
            "Complaint / FIR / reference number",
            value=case.get("police_complaint_number") or "",
            key=f"pv-number-{case['case_id']}",
        )
        date = st.text_input(
            "Complaint date (DD/MM/YYYY or YYYY-MM-DD)",
            value=case.get("police_complaint_date") or "",
            key=f"pv-date-{case['case_id']}",
        )
        complaint_station = st.text_input(
            "Police station",
            value=case.get("authorized_station") or user.get("station") or "",
            key=f"pv-station-{case['case_id']}",
        )
        notes = st.text_area(
            "Verification notes (internal — not shown to parent)",
            key=f"pv-notes-{case['case_id']}",
        )
        submitted = st.form_submit_button("✅ Verify and Activate Case")
    if submitted:
        try:
            store.verify_police_complaint(
                user["username"], case["case_id"],
                number, date, complaint_station, notes,
            )
            st.success(
                f"Case {case['case_id']} is now ACTIVE and cleared for CCTV processing."
            )
            st.rerun()
        except Exception as exc:
            show_error(st, exc)


def _render_station_section(st, store, user, case) -> None:
    try:
        assignments = store.list_station_assignments(user["username"], case["case_id"])
        with st.expander("Station assignments"):
            st.write(
                [{"station": case["authorized_station"], "status": "ORIGINAL"}]
                + [{"station": a["station_code"], "status": a["assignment_status"]} for a in assignments]
            )
            with st.form(f"station-assign-{case['case_id']}"):
                station = st.text_input("Station code", key=f"sa-code-{case['case_id']}")
                state = st.selectbox(
                    "Status", ["ACTIVE", "PENDING", "CLOSED"], key=f"sa-state-{case['case_id']}"
                )
                if st.form_submit_button("Save assignment"):
                    try:
                        store.assign_station(user["username"], case["case_id"], station, state)
                        st.success("Station assignment saved.")
                        st.rerun()
                    except Exception as exc:
                        show_error(st, exc)
    except Exception:
        pass


# ── CCTV Analysis ──────────────────────────────────────────────────────────────

def _render_cctv_analysis(st, store, user) -> None:
    st.subheader("CCTV Analysis")
    st.caption(
        "Upload CCTV footage for an ACTIVE case, then run the existing "
        "YOLO → DeepSORT → InsightFace pipeline. "
        "All results begin as **PENDING** and require authorized human review."
    )

    # CCTV upload form
    with st.expander("📤 Upload CCTV Footage", expanded=True):
        _render_cctv_upload(st, store, user)

    st.divider()

    # Pending submissions — show "Run AI Analysis" for ACTIVE cases
    st.subheader("Stored Footage Ready for Analysis")
    _render_pending_submissions(st, store, user)


def _render_cctv_upload(st, store, user) -> None:
    try:
        cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    active_cases = [c for c in cases if (c.get("lifecycle_state") or c.get("case_status")) == "ACTIVE"]
    if not active_cases:
        st.info(
            "No ACTIVE cases available. Police must verify a complaint before "
            "CCTV footage can be processed."
        )
        return

    with st.form("cctv-police-upload"):
        case_options = {f"{c['case_id']} — {c['child_name']}": c["case_id"] for c in active_cases}
        selected_label = st.selectbox("Select ACTIVE case", list(case_options.keys()))
        selected_case_id = case_options[selected_label]
        location = st.text_input("Station / location", value=user.get("station") or "")
        capture_time = st.text_input("Capture date/time (optional)")
        description = st.text_area("Description (optional)")
        upload = st.file_uploader("CCTV video", type=["mp4", "avi", "mov"])
        submit = st.form_submit_button("📥 Store for Analysis")

    if submit:
        try:
            if upload is None:
                raise ValueError("Select an MP4, AVI, or MOV video first.")
            store.submit_cctv(
                user["username"], selected_case_id, location,
                upload.name, upload.getvalue(), capture_time, description,
            )
            st.success(
                f"CCTV footage stored for case {selected_case_id}. "
                "Scroll down to run AI analysis."
            )
            st.rerun()
        except Exception as exc:
            show_error(st, exc)


def _render_pending_submissions(st, store, user) -> None:
    from services.pipeline_service import list_pending_cctv_submissions

    try:
        submissions = list_pending_cctv_submissions(user["username"], store)
    except Exception as exc:
        show_error(st, exc)
        return

    if not submissions:
        st.info("No stored CCTV submissions yet.")
        return

    for sub in submissions:
        lifecycle = sub.get("lifecycle_state") or sub.get("case_status") or ""
        is_active = lifecycle == "ACTIVE"
        label = (
            f"✅ {sub['case_id']} | {sub['stored_name']}"
            if is_active
            else f"⏳ {sub['case_id']} | {sub['stored_name']} [case not ACTIVE]"
        )
        with st.expander(label):
            st.write({
                "Case": sub["case_id"],
                "Uploaded by": sub["uploading_user"],
                "File": sub["stored_name"],
                "Captured": sub.get("capture_datetime") or "—",
                "Description": sub.get("description") or "—",
                "Stored": sub.get("created_at", "")[:19],
                "Processing status": sub.get("processing_status", "—"),
                "Case status": lifecycle,
            })
            if not is_active:
                st.warning(
                    "This case is not ACTIVE. Police must verify the complaint before "
                    "AI analysis can run."
                )
                continue

            if st.button(
                "🤖 Run AI Analysis",
                key=f"run-ai-{sub['id']}",
                type="primary",
            ):
                _run_pipeline_with_progress(st, store, user, sub)


def _run_pipeline_with_progress(st, store, user, submission) -> None:
    """Invoke the existing pipeline with live progress display."""
    from services.pipeline_service import run_cctv_analysis

    progress_log: list[str] = []

    def callback(msg: str) -> None:
        progress_log.append(msg)

    with st.status("Running AI analysis…", expanded=True) as status_widget:
        st.write("🔄 Loading child reference…")
        try:
            result = run_cctv_analysis(
                actor=user["username"],
                store=store,
                case_id=submission["case_id"],
                stored_video_name=submission["stored_name"],
                progress_callback=lambda msg: st.write(f"  {msg}"),
            )
            st.write("✅ Pipeline complete.")
            status_widget.update(label="AI analysis complete", state="complete", expanded=True)
        except Exception as exc:
            status_widget.update(label="Analysis failed", state="error", expanded=True)
            show_error(st, exc)
            return

    st.divider()
    st.subheader("CCTV Analysis Complete")
    match_count = result.get("potential_matches", 0)
    col1, col2 = st.columns(2)
    col1.metric("Potential Matches Found", match_count)
    col2.metric("Match Status", "PENDING HUMAN REVIEW" if match_count > 0 else "None")

    if match_count > 0:
        st.success(
            f"**{match_count} potential match(es) recorded as PENDING.**\n\n"
            "An authorized reviewer must evaluate the evidence before any action is taken. "
            "**AI has not confirmed a child has been found.**"
        )
        st.info(
            "Parent has been notified: 'Potential match under review — "
            "an authorized investigator is reviewing the available evidence.'"
        )
    else:
        st.info(
            "No potential matches crossed the configured evidence threshold in this footage. "
            "The pipeline ran successfully. A zero-match result does not prove absence."
        )


# ── Police matches view ────────────────────────────────────────────────────────

def _render_police_matches(st, store, user) -> None:
    st.subheader("Potential Matches")
    st.caption(
        "These are PENDING AI-generated potential matches requiring authorized human review."
    )
    try:
        matches = store.list_matches(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    if not matches:
        st.info("No potential matches available.")
        return

    pending = [m for m in matches if m.get("status") == "PENDING"]
    reviewed = [m for m in matches if m.get("status") != "PENDING"]

    col1, col2 = st.columns(2)
    col1.metric("Pending Review", len(pending))
    col2.metric("Reviewed", len(reviewed))

    st.subheader("Pending Review")
    for match in pending:
        with st.expander(f"Potential Match #{match['id']} — {match['case_id']}"):
            status_badge(st, match["status"])
            st.write({
                k: match.get(k)
                for k in ("case_id", "child_id", "track_id", "frame_number",
                           "video_name", "overall_score", "created_at")
            })
            st.caption(
                "⚠️ This is a PENDING potential match. "
                "An authorized REVIEWER must evaluate the evidence."
            )

    if reviewed:
        with st.expander("Previously reviewed matches"):
            for match in reviewed:
                st.caption(
                    f"Match #{match['id']} ({match['case_id']}) — "
                    f"{match['status']} by {match.get('reviewed_by') or '—'}"
                )
