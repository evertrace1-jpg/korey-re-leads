"""Bankroll tracker — equity curve from $5,000 + running P&L."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from utils import db, tasty
from utils.auth import require_password

st.set_page_config(page_title="Bankroll", page_icon="💰", layout="wide")
require_password()
st.title("💰 Bankroll Tracker")

with st.spinner("Loading…"):
    bal = tasty.fetch_balances()
    db.record_snapshot(bal["net_liquidating_value"], bal["cash_balance"])
    curve = db.equity_curve()
    trades = db.all_trades()

nlv = bal["net_liquidating_value"]
total_pl = nlv - config.STARTING_BANKROLL
pct = (total_pl / config.STARTING_BANKROLL * 100.0) if config.STARTING_BANKROLL else 0.0
realized = float(trades["pl"].dropna().sum()) if not trades.empty else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Starting Bankroll", f"${config.STARTING_BANKROLL:,.2f}")
c2.metric("Current NLV", f"${nlv:,.2f}", f"{pct:+.2f}%")
c3.metric("Total P/L", f"${total_pl:,.2f}")
c4.metric("Realized P/L (journal)", f"${realized:,.2f}")

st.divider()

if curve.empty:
    st.info("No snapshots yet. Visit the Open Positions or main page to record one.")
    st.stop()

# Build equity curve with starting line
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=curve["taken_at"],
        y=curve["nlv"],
        mode="lines+markers",
        name="NLV",
        line={"color": "#22c55e", "width": 2},
    )
)
fig.add_hline(
    y=config.STARTING_BANKROLL,
    line_dash="dash",
    line_color="#9ca3af",
    annotation_text=f"start ${config.STARTING_BANKROLL:,.0f}",
)
fig.update_layout(
    template="plotly_dark",
    height=480,
    margin={"l": 10, "r": 10, "t": 30, "b": 10},
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis_title=None,
    yaxis_title="NLV ($)",
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Recent snapshots")
st.dataframe(
    curve.tail(50).iloc[::-1].reset_index(drop=True),
    use_container_width=True,
    height=300,
)
