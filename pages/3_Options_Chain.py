"""Live option chain viewer — pulls from Tastytrade."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from utils import tasty
from utils.auth import require_password

st.set_page_config(page_title="Options Chain", page_icon="⛓️", layout="wide")
require_password()
st.title("⛓️ Options Chain Viewer")

col1, col2 = st.columns([1, 3])
with col1:
    symbol = st.text_input("Ticker", value="SPY").strip().upper()
    side = st.radio("Side", ["Both", "Calls", "Puts"], horizontal=True)
with col2:
    st.caption("Live chain from Tastytrade. IV / delta / mark may be empty "
               "outside RTH or for illiquid strikes.")

if not symbol:
    st.stop()

with st.spinner(f"Loading {symbol} chain…"):
    try:
        chain = tasty.fetch_option_chain(symbol)
    except Exception as e:
        st.error(f"Chain fetch failed: {e}")
        st.stop()

if not chain:
    st.warning("No chain returned.")
    st.stop()

expirations = sorted(chain.keys())
exp_labels = [f"{e.isoformat()}  ({(e - dt.date.today()).days}d)" for e in expirations]
idx = st.select_slider(
    "Expiration",
    options=list(range(len(expirations))),
    value=0,
    format_func=lambda i: exp_labels[i],
)
exp = expirations[idx]
options = chain[exp]


def _row(o):
    opt_type = str(getattr(o, "option_type", "")).upper()
    return {
        "type": "C" if opt_type.startswith("C") else "P",
        "strike": float(getattr(o, "strike_price", 0) or 0),
        "symbol": getattr(o, "symbol", ""),
        "streamer_symbol": getattr(o, "streamer_symbol", ""),
        "expires_at": getattr(o, "expiration_date", ""),
    }


df = pd.DataFrame([_row(o) for o in options]).sort_values(["strike", "type"])

if side == "Calls":
    df = df[df["type"] == "C"]
elif side == "Puts":
    df = df[df["type"] == "P"]

st.caption(
    f"{len(df)} contracts for {symbol} expiring {exp}. "
    "Streaming IV/delta/premium requires the DXFeed websocket — wire "
    "`tastytrade.streamer.DXLinkStreamer` in if you need live greeks."
)
st.dataframe(df, use_container_width=True, height=600)
