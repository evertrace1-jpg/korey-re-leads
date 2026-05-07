"""Unusual options flow — best-effort Barchart scrape."""
from __future__ import annotations

import streamlit as st

from utils import flow
from utils.auth import require_password

st.set_page_config(page_title="Unusual Flow", page_icon="🌊", layout="wide")
require_password()
st.title("🌊 Unusual Options Flow")

if st.button("🔄 Force refresh"):
    flow.fetch_unusual_flow.clear()

with st.spinner("Pulling Barchart…"):
    df, note = flow.fetch_unusual_flow()

st.caption(f"Source: {note}")

if df.empty:
    st.info(
        "No flow rows available. Barchart's free page is JS-rendered and "
        "login-gated, so the static scrape rarely returns data. To make this "
        "panel reliable, plug in a paid feed in `utils/flow.py` "
        "(Cheddar Flow, FlowAlgo, BlackBoxStocks, or Barchart's premium API)."
    )
    st.stop()

st.dataframe(df, use_container_width=True, height=700)
