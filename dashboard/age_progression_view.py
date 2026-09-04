"""Age-progression initiation UI for authorized POLICE and REVIEWER roles.

This module only calls existing service methods from age_progression.py
and review_store.py. It does not contain AI or genetic-prediction logic.

The provider boundary is explicit:
  - If no real provider is configured → shows UNAVAILABLE status clearly.
  - Development placeholder → labeled as non-predictive.
  - All candidates begin PENDING_REVIEW and require reviewer approval.
"""

from __future__ import annotations

from dashboard.components import show_error


def render_age_progression(st, store, user) -> None:
    st.header("Age Progression")
    st.caption(
        "Parent/guardian reference photos are appearance-only inputs, "
        "not genetic predictions. "
        "All generated candidates begin PENDING_REVIEW and require authorized reviewer approval."
    )

    _render_provider_status(st)
    st.divider()
    _render_initiation_form(st, store, user)
    st.divider()
    _render_pending_candidates(st, store, user)


def _render_provider_status(st) -> None:
    """Show the configured age-progression provider status clearly."""
    import os  # noqa: PLC0415
    provider_env = os.getenv("AGE_PROGRESSION_PROVIDER", "").strip().upper()
    if provider_env in ("", "UNAVAILABLE", "NONE"):
        st.warning(
            "**Age Progression Provider: NOT CONFIGURED**\n\n"
            "A real age-progression provider is not configured in this environment. "
            "A development placeholder is available for demonstration only — "
            "it does not transform the image, claim any age prediction, "
            "or infer any genetic characteristics. "
            "The placeholder result still requires authorized reviewer approval before use."
        )
    else:
        st.info(f"Age Progression Provider: **{provider_env}**")


def _render_initiation_form(st, store, user) -> None:
    st.subheader("Request Age Progression Candidate")

    try:
        cases = store.list_cases(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    eligible = [c for c in cases if (c.get("lifecycle_state") or c.get("case_status")) == "ACTIVE"]
    if not eligible:
        st.info("No ACTIVE cases available for age-progression requests.")
        return

    case_options = {f"{c['case_id']} — {c['child_name']}": c["case_id"] for c in eligible}

    with st.form("age-progression-request"):
        selected_label = st.selectbox("Select ACTIVE case", list(case_options.keys()))
        selected_case_id = case_options[selected_label]
        target_age = st.number_input("Target age (years)", min_value=1, max_value=120, step=1, value=10)
        use_placeholder = st.checkbox(
            "Use development placeholder (no real prediction — demonstration only)",
            value=True,
        )
        st.caption(
            "⚠️ The development placeholder returns the original child image unchanged. "
            "It makes no age prediction and infers no genetic characteristics. "
            "A reviewer must still approve it before it can be used."
        )
        submit = st.form_submit_button("Request Age Progression Candidate")

    if submit:
        _handle_request(st, store, user, selected_case_id, int(target_age), use_placeholder)


def _handle_request(st, store, user, case_id, target_age, use_placeholder) -> None:
    from services.config import EVIDENCE_DIR  # noqa: PLC0415
    from services.evidence_crypto import EvidenceCrypto  # noqa: PLC0415
    from services.evidence_storage import EvidenceStorage  # noqa: PLC0415
    from services.age_progression import AgeProgressionService, DevelopmentPlaceholderProvider, ProviderUnavailable  # noqa: PLC0415

    # Resolve child reference
    try:
        with store._connection() as db:  # noqa: SLF001
            ref_row = db.execute(
                "SELECT id, opaque_reference FROM child_reference_images "
                "WHERE case_id=? AND status='ACTIVE' ORDER BY id LIMIT 1",
                (case_id,),
            ).fetchone()
        if not ref_row:
            st.error(
                "No active child reference image found for this case. "
                "Upload a child photograph first."
            )
            return
        child_ref_id = ref_row[0]
        opaque_child_ref = str(ref_row[1])
    except Exception as exc:
        show_error(st, exc)
        return

    # Resolve parent references
    try:
        parent_refs = store.list_parent_references(user["username"], case_id)
    except Exception:
        parent_refs = []

    storage = EvidenceStorage(EVIDENCE_DIR, EvidenceCrypto())
    try:
        child_image = storage.read_controlled(opaque_child_ref)
    except Exception as exc:
        show_error(st, exc)
        return

    parent_images: list[bytes] = []
    for ref in parent_refs:
        try:
            parent_images.append(storage.read_controlled(str(ref.get("opaque_reference", ""))))
        except Exception:
            pass

    # Build provider
    provider = DevelopmentPlaceholderProvider() if use_placeholder else ProviderUnavailable()
    service = AgeProgressionService(store, storage, provider)

    try:
        result = service.request(
            actor=user["username"],
            case_id=case_id,
            child_reference_id=child_ref_id,
            target_age=target_age,
            child_image=child_image,
            parent_images=parent_images,
        )
        st.success(
            f"Age-progression candidate created — ID: {result['id']}\n\n"
            f"**Status: PENDING_REVIEW**\n\n"
            f"Provider: {result['provider']}\n\n"
            f"An authorized REVIEWER must approve this candidate before it can be used "
            f"as a matching reference."
        )
        if use_placeholder:
            st.warning(
                "**DEVELOPMENT PLACEHOLDER — AVAILABLE FOR DEMONSTRATION ONLY**\n\n"
                "This candidate was generated by the development placeholder. "
                "It is not an age prediction and must not be represented as one."
            )
        st.rerun()
    except Exception as exc:
        show_error(st, exc)


def _render_pending_candidates(st, store, user) -> None:
    st.subheader("Pending Age-Progression Candidates")
    st.caption("Only REVIEWER and ADMIN roles can approve or reject candidates.")

    try:
        candidates = store.list_pending_age_progression_references(user["username"])
    except Exception as exc:
        show_error(st, exc)
        return

    if not candidates:
        st.info("No candidates are currently awaiting review.")
        return

    for candidate in candidates:
        with st.expander(
            f"Candidate #{candidate['id']} — Case {candidate['case_id']} "
            f"(target age {candidate['target_age']})"
        ):
            st.write({
                "Case": candidate["case_id"],
                "Target age": candidate["target_age"],
                "Provider": candidate.get("provider"),
                "Status": candidate.get("status"),
                "Requested": (candidate.get("created_at") or "")[:19],
            })
            if candidate.get("provider") == "DEVELOPMENT_PLACEHOLDER_NO_GENETIC_PREDICTION":
                st.warning(
                    "⚠️ **DEVELOPMENT PLACEHOLDER** — no real age prediction. "
                    "For demonstration only."
                )
            if user["role"] in {"ADMIN", "REVIEWER"}:
                col1, col2 = st.columns(2)
                if col1.button("✅ Approve", key=f"ap-approve-{candidate['id']}"):
                    try:
                        store.review_age_progression_reference(
                            user["username"], candidate["id"], True
                        )
                        st.success("Candidate approved — a matching reference can now be generated.")
                        st.rerun()
                    except Exception as exc:
                        show_error(st, exc)
                if col2.button("❌ Reject", key=f"ap-reject-{candidate['id']}"):
                    try:
                        store.review_age_progression_reference(
                            user["username"], candidate["id"], False
                        )
                        st.info("Candidate rejected.")
                        st.rerun()
                    except Exception as exc:
                        show_error(st, exc)
            else:
                st.caption("REVIEWER or ADMIN role required to approve or reject.")
