"""No Kite account requests occur until the owner re-enters the password."""

import streamlit as st

from core.report_access import kite_token, kite_unlocked

TOKEN = "tf_kite_window_token"
FIELD = "tf_kite_window_password"
ERROR = "tf_kite_window_error"


def unlock():
    supplied = st.session_state.get(FIELD, "")
    st.session_state[FIELD] = ""
    try:
        st.session_state[TOKEN] = kite_token(supplied)
        st.session_state.pop(ERROR, None)
    except ValueError:
        st.session_state.pop(TOKEN, None)
        st.session_state[ERROR] = "Unable to unlock. Check the TrendForge password."


def require_kite_window():
    if kite_unlocked(st.session_state.get(TOKEN)):
        if st.button("Lock Kite window", key="tf_lock_kite_window"):
            st.session_state.pop(TOKEN, None)
            st.rerun()
        return
    st.info(
        "Re-enter your TrendForge password to access the Kite "
        "window. Access expires after 15 "
        "minutes."
    )
    with st.form("kite_window_unlock"):
        st.text_input("Kite window password", type="password", key=FIELD)
        st.form_submit_button("Unlock Kite window", on_click=unlock)
    if st.session_state.get(ERROR):
        st.error(st.session_state[ERROR])
    st.stop()
