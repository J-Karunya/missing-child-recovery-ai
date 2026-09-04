"""Shared Streamlit helpers for the local prototype dashboard."""

from __future__ import annotations

from services.session_service import SessionService
from services.mfa_service import MFAService
from services.review_store import AuthorizationError, ReviewStore, ValidationError


def require_authenticated_user(st, store: ReviewStore) -> dict | None:
    """Validate a short-lived non-secret Streamlit session on every rerun."""
    session = st.session_state.get("auth_session")
    if not session:
        return None
    try:
        user = SessionService(store).validate(str(session["token"]))
    except (KeyError, ValueError, AuthorizationError):
        st.session_state.pop("auth_session", None)
        st.warning("Your session is no longer authorized. Please sign in again.")
        return None
    return user


def login_screen(st, store: ReviewStore) -> dict | None:
    st.title("Missing Child Recovery AI")
    st.caption("Authorized access only. AI creates potential matches; humans review them.")
    with st.form("login"):
        identity = st.text_input("Username or email")
        password = st.text_input("Password", type="password")
        mfa_code = st.text_input("MFA code (only if your account requires it)", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        user = store.authenticate(identity, password)
        if not user:
            st.error("Invalid credentials.")
        elif user.get("mfa_enabled") and not MFAService(store).verify_login(user["id"], mfa_code):
            st.error("Invalid credentials.")
        else:
            st.session_state["auth_session"] = {"token": SessionService(store).create(user["id"])}
            st.rerun()
    return None


def logout_button(st, store: ReviewStore, user: dict) -> None:
    if st.sidebar.button("Sign out"):
        try:
            session = st.session_state.get("auth_session") or {}
            if session.get("token"):
                SessionService(store).revoke(str(session["token"]))
            store.record_logout(user["id"])
        finally:
            st.session_state.pop("auth_session", None)
        st.rerun()


def status_badge(st, status: str) -> None:
    colors = {"PENDING": "orange", "VERIFIED": "green", "REJECTED": "red", "ACTIVE": "green", "PAUSED": "orange", "CLOSED": "gray"}
    st.markdown(f":{colors.get(status, 'blue')}[{status}]")


def show_error(st, error: Exception) -> None:
    if isinstance(error, (ValidationError, AuthorizationError)):
        st.error(str(error))
    else:
        st.error("The requested operation could not be completed. Check the stored data and try again.")
