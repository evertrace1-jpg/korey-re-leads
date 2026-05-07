"""Trading Dashboard — main landing page.

Streamlit auto-discovers files in pages/ for the sidebar.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

import config
from utils import db, tasty
from utils.auth import require_password

st.set_page_config(
    page_title="Options Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

require_password()
db.init_db()


def _market_open(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


# Auto-refresh during market hours (Streamlit native rerun)
if _market_open():
    st.markdown(
        f"<meta http-equiv='refresh' content='{config.REFRESH_MINUTES * 60}'>",
        unsafe_allow_html=True,
    )

st.title("📈 Options Trading Dashboard")

env_badge = "🟢 PAPER" if config.IS_PAPER else "🔴 LIVE"
st.caption(
    f"{env_badge}  ·  refresh every {config.REFRESH_MINUTES} min during market hours  "
    f"·  starting bankroll ${config.STARTING_BANKROLL:,.0f}"
)

with st.spinner("Connecting to Tastytrade…"):
    try:
        label = tasty.account_label()
        bal = tasty.fetch_balances()
    except Exception as e:
        st.error(f"Tastytrade connection failed: {e}")
        st.stop()

st.success(f"Connected: {label}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net Liq", f"${bal['net_liquidating_value']:,.2f}")
c2.metric("Cash", f"${bal['cash_balance']:,.2f}")
c3.metric("Equity BP", f"${bal['equity_buying_power']:,.2f}")
c4.metric("Deriv BP", f"${bal['derivative_buying_power']:,.2f}")

# Snapshot for equity curve
db.record_snapshot(
    nlv=bal["net_liquidating_value"],
    cash=bal["cash_balance"],
)

st.divider()
st.markdown("### Panels")
st.markdown(
    "- **Earnings Radar** — next 60 days of earnings, sorted by IV rank\n"
    "- **Unusual Flow** — large OTM bets scraped from Barchart\n"
    "- **Options Chain** — live chain for any ticker\n"
    "- **Open Positions** — live P&L + loss alerts\n"
    "- **Bankroll** — equity curve from $5,000\n"
    "- **Trade Journal** — log entries, exits, theses, results"
)

st.caption(f"Last refresh: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
