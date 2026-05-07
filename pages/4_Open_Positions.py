"""Open positions — live P&L + macOS notification on -50% drawdown."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import notify, tasty
from utils.auth import require_password

st.set_page_config(page_title="Open Positions", page_icon="💼", layout="wide")
require_password()
st.title("💼 Open Positions")

threshold = st.sidebar.slider(
    "Loss alert threshold (%)",
    min_value=-90,
    max_value=-10,
    value=-50,
    step=5,
)
test_alert = st.sidebar.button("🔔 Test notification")
if test_alert:
    notify.notify(
        "Trading Dashboard",
        "Test notification — alerts are working.",
    )
    st.sidebar.success("Notification sent (check Notification Center).")

with st.spinner("Pulling positions…"):
    try:
        rows = tasty.fetch_positions()
    except Exception as e:
        st.error(f"Position fetch failed: {e}")
        st.stop()

if not rows:
    st.info("No open positions.")
    st.stop()

df = pd.DataFrame([r.__dict__ for r in rows])

# Trigger native alerts for any losers past threshold
for r in rows:
    notify.maybe_alert_loss(r.symbol, r.unrealized_pl_pct, threshold=threshold)

total_mv = df["market_value"].sum()
total_pl = df["unrealized_pl"].sum()
total_cost = df["cost_basis"].sum()
pct = (total_pl / total_cost * 100.0) if total_cost else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("Market Value", f"${total_mv:,.2f}")
c2.metric("Cost Basis", f"${total_cost:,.2f}")
c3.metric("Unrealized P/L", f"${total_pl:,.2f}", f"{pct:+.2f}%")


def _color(v):
    if v > 0:
        return "color: #22c55e"
    if v < 0:
        return "color: #ef4444"
    return ""


display = df[
    [
        "symbol", "underlying", "instrument_type", "quantity", "direction",
        "avg_open_price", "mark", "cost_basis", "market_value",
        "unrealized_pl", "unrealized_pl_pct",
    ]
].rename(columns={
    "instrument_type": "type",
    "avg_open_price": "avg",
    "cost_basis": "cost",
    "market_value": "mv",
    "unrealized_pl": "P/L $",
    "unrealized_pl_pct": "P/L %",
})

st.dataframe(
    display.style
        .format({
            "avg": "{:.2f}",
            "mark": "{:.2f}",
            "cost": "${:,.2f}",
            "mv": "${:,.2f}",
            "P/L $": "${:,.2f}",
            "P/L %": "{:+.2f}%",
        })
        .map(_color, subset=["P/L $", "P/L %"]),
    use_container_width=True,
    height=600,
)

losers = [r for r in rows if r.unrealized_pl_pct <= threshold]
if losers:
    st.warning(
        f"⚠️ {len(losers)} position(s) past {threshold}%: "
        + ", ".join(f"{r.symbol} ({r.unrealized_pl_pct:.1f}%)" for r in losers)
    )
