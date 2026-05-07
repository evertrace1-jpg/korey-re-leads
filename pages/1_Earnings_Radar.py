"""Earnings radar — next 60 days, color coded by setup quality."""
from __future__ import annotations

import streamlit as st

from utils import earnings
from utils.auth import require_password

st.set_page_config(page_title="Earnings Radar", page_icon="📅", layout="wide")
require_password()
st.title("📅 Earnings Radar")
st.caption(
    "Next 60 days of earnings from a curated watchlist. "
    "IV rank is a 20d realized-vol-rank proxy (true IVR needs paid options-IV history)."
)

with st.sidebar:
    st.subheader("Watchlist")
    default = "\n".join(earnings.DEFAULT_WATCHLIST)
    raw = st.text_area("One ticker per line", value=default, height=300)
    tickers = [t.strip().upper() for t in raw.splitlines() if t.strip()]
    if st.button("🔄 Force refresh"):
        earnings.scan_earnings.clear()

with st.spinner(f"Scanning {len(tickers)} tickers…"):
    df = earnings.scan_earnings(tickers, window_days=60)

if df.empty:
    st.warning("No upcoming earnings found in window. Try a larger watchlist.")
    st.stop()


def _row_style(row):
    color_map = {
        "green": "background-color: rgba(34,197,94,0.18)",
        "yellow": "background-color: rgba(234,179,8,0.18)",
        "red": "background-color: rgba(239,68,68,0.18)",
    }
    return [color_map.get(row["color"], "")] * len(row)


display = df[
    [
        "ticker", "earnings_date", "days_until", "iv_rank",
        "expected_move_pct", "last_move_pct",
        "analyst_high", "analyst_low", "analyst_spread_pct", "color",
    ]
].rename(columns={
    "iv_rank": "IVR",
    "expected_move_pct": "Exp Move %",
    "last_move_pct": "Last Move %",
    "analyst_high": "Tgt Hi",
    "analyst_low": "Tgt Lo",
    "analyst_spread_pct": "Tgt Spread %",
})

st.dataframe(
    display.style.apply(_row_style, axis=1),
    use_container_width=True,
    height=600,
)

st.caption(
    "🟢 IVR ≥ 60 + tight analyst spread (≤15%)   "
    "🟡 IVR ≥ 40   "
    "🔴 low IVR / wide spread"
)
