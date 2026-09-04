"""Case management page; it only calls ReviewStore service methods."""

from __future__ import annotations

from dashboard.components import show_error, status_badge
from services.config import EVIDENCE_DIR
from services.evidence_crypto import EvidenceCrypto
from services.evidence_storage import EvidenceStorage


def render_cases(st, store, user) -> None:
    st.header("Cases")
    try:
        cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return
    if user["role"] == "PARENT":
        with st.expander("Register Missing Child Case"):
            st.caption("A submitted report awaits police verification. It does not activate CCTV processing.")
            with st.form("parent-report"):
                case_id = st.text_input("Report ID", placeholder="REPORT001")
                child_id = st.text_input("Child ID", placeholder="CHILD001")
                name = st.text_input("Child name")
                age = st.number_input("Child's current age", min_value=0, step=1)
                description = st.text_area("Description")
                last_seen = st.text_input("Last seen location")
                station = st.text_input("Police station", value="HQ")
                complaint_number = st.text_input("Police complaint/reference number (if available)")
                complaint_date = st.text_input("Complaint date (if available)")
                photo = st.file_uploader("Recent child photograph", type=["jpg", "jpeg", "png"])
                submitted = st.form_submit_button("Submit report")
            if submitted:
                try:
                    if photo is None:
                        raise ValueError("A recent child photograph is required.")
                    store.validate_reference_upload(photo.name, photo.getvalue())
                    report = store.create_preliminary_report(user["username"], {"case_id": case_id, "child_id": child_id, "child_name": name, "age": int(age), "description": description, "reference_image": photo.name, "authorized_station": station, "last_seen_location": last_seen, "police_complaint_number": complaint_number or "UNVERIFIED", "police_complaint_date": complaint_date, "complaint_police_station": station})
                    opaque = EvidenceStorage(EVIDENCE_DIR, EvidenceCrypto()).store_controlled("child_reference", 0, photo.getvalue())
                    store.add_child_reference(user["username"], report["case_id"], photo.name, opaque)
                    st.success("Report submitted and awaiting police verification.")
                    st.rerun()
                except Exception as exc:
                    show_error(st, exc)
        with st.expander("Upload Recent Parent/Guardian Reference Photo"):
            with st.form("parent-reference"):
                case_id = st.text_input("Report ID")
                relationship = st.selectbox("Reference", ["Parent/Guardian 1", "Parent/Guardian 2", "Historical family reference"])
                photo = st.file_uploader("Reference photograph", type=["jpg", "jpeg", "png"], key="parent-reference-file")
                submitted = st.form_submit_button("Store controlled reference")
            if submitted:
                try:
                    if photo is None:
                        raise ValueError("Select a reference photograph first.")
                    store.validate_reference_upload(photo.name, photo.getvalue())
                    opaque = EvidenceStorage(EVIDENCE_DIR, EvidenceCrypto()).store_controlled("parent_reference", 0, photo.getvalue())
                    store.add_parent_reference(user["username"], case_id, relationship, photo.name, opaque)
                    st.success("Reference stored with controlled encrypted storage.")
                    st.rerun()
                except Exception as exc:
                    show_error(st, exc)
    if user["role"] in {"ADMIN", "POLICE"}:
        with st.expander("Create authorized case"):
            with st.form("create-case"):
                case_id = st.text_input("Case ID", placeholder="CASE001")
                child_id = st.text_input("Child ID", placeholder="MC001")
                name = st.text_input("Child name")
                age = st.number_input("Age", min_value=0, step=1)
                description = st.text_area("Description")
                reference = st.text_input("Reference image filename", placeholder="child1.jpeg")
                station = st.text_input("Authorized station", value=user.get("station") or "HQ")
                parent = st.text_input("Parent username (optional)", placeholder="parent_demo")
                submitted = st.form_submit_button("Create case")
            if submitted:
                try:
                    store.create_case(user["username"], {"case_id": case_id, "child_id": child_id, "child_name": name, "age": int(age), "description": description, "reference_image": reference, "authorized_station": station, "parent_username": parent or None})
                    st.success("Case created.")
                    st.rerun()
                except Exception as exc:
                    show_error(st, exc)
    if user["role"] in {"ADMIN", "POLICE", "REVIEWER"}:
        try:
            pending_candidates = store.list_pending_age_progression_references(user["username"])
            if pending_candidates:
                st.subheader("Pending age-progression candidates")
                for candidate in pending_candidates:
                    st.caption(f"Case {candidate['case_id']} · target age {candidate['target_age']} · pending reviewer approval")
                    left, right = st.columns(2)
                    if left.button("Approve candidate", key=f"approve-progression-{candidate['id']}"):
                        store.review_age_progression_reference(user["username"], candidate["id"], True)
                        st.rerun()
                    if right.button("Reject candidate", key=f"reject-progression-{candidate['id']}"):
                        store.review_age_progression_reference(user["username"], candidate["id"], False)
                        st.rerun()
        except Exception as exc:
            show_error(st, exc)
    if not cases:
        st.info("No cases are available for this role.")
        return
    for case in cases:
        with st.expander(f"{case['case_id']} — {case['child_name']}"):
            status_badge(st, case["case_status"])
            st.write({key: value for key, value in case.items() if key not in {"description", "reference_image", "parent_username"} or user["role"] != "PARENT"})
            if user["role"] in {"ADMIN", "POLICE"}:
                if (case.get("lifecycle_state") or case["case_status"]) == "PENDING_POLICE_VERIFICATION":
                    st.subheader("Police Complaint Verification")
                    with st.form(f"verify-{case['case_id']}"):
                        number = st.text_input("Complaint/FIR/reference number", key=f"complaint-{case['case_id']}")
                        date = st.text_input("Complaint date", key=f"date-{case['case_id']}")
                        complaint_station = st.text_input("Complaint police station", value=case.get("authorized_station") or "", key=f"complaint-station-{case['case_id']}")
                        notes = st.text_area("Verification notes (internal)", key=f"notes-{case['case_id']}")
                        verify = st.form_submit_button("Verify and activate case")
                    if verify:
                        try:
                            store.verify_police_complaint(user["username"], case["case_id"], number, date, complaint_station, notes)
                            st.success("Case verified and activated for authorized processing.")
                            st.rerun()
                        except Exception as exc:
                            show_error(st, exc)
                try:
                    assignments = store.list_station_assignments(user["username"], case["case_id"])
                    st.caption("Authorized stations receive staff notifications for this case.")
                    st.write([{"station": case["authorized_station"], "status": "ORIGINAL"}] + [{"station": item["station_code"], "status": item["assignment_status"]} for item in assignments])
                    with st.form(f"station-{case['case_id']}"):
                        station = st.text_input("Station code", key=f"station-code-{case['case_id']}")
                        state = st.selectbox("Assignment status", ["ACTIVE", "PENDING", "CLOSED"], key=f"station-state-{case['case_id']}")
                        submitted = st.form_submit_button("Save station assignment")
                    if submitted:
                        store.assign_station(user["username"], case["case_id"], station, state)
                        st.success("Station assignment recorded and audited.")
                        st.rerun()
                except Exception as exc:
                    show_error(st, exc)
            if user["role"] == "PARENT":
                st.caption(case.get("police_verification_status", "Pending police verification"))
                try:
                    references = store.list_parent_references(user["username"], case["case_id"])
                    st.write({"parent_reference_count": len(references), "age_progression": "Provider must be configured; generated references always require human review."})
                except Exception as exc:
                    show_error(st, exc)
