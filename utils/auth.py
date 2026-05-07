"""Password gate for Streamlit pages.

Reads the expected password from .streamlit/secrets.toml. Each page calls
require_password() at the top — once authenticated, st.session_state carries
the flag across page navigations within the same browser session.
"""
from __future__ import annotations

import hmac

import streamlit as st


def require_password() -> None:
    if st.session_state.get("auth_ok"):
        return

    try:
        expected = st.secrets.get("password")
    except Exception:
        expected = None

    if not expected:
        st.error(
            "Server misconfigured: no `password` in .streamlit/secrets.toml. "
            "Run start_remote.sh again or set one manually."
        )
        st.stop()

    def _check() -> None:
        if hmac.compare_digest(st.session_state.get("_pw", ""), expected):
            st.session_state["auth_ok"] = True
            del st.session_state["_pw"]
            st.session_state.pop("auth_failed", None)
        else:
            st.session_state["auth_failed"] = True

    st.title("🔐 Dashboard Locked")
    st.text_input("Password", type="password", key="_pw", on_change=_check)
    if st.button("Unlock", type="primary", use_container_width=True):
        _check()
        if st.session_state.get("auth_ok"):
            st.rerun()
    if st.session_state.get("auth_failed"):
        st.error("Incorrect password.")
    st.stop()
