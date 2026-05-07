"""Trade journal — log entry, exit, P&L, thesis, result."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from utils import db
from utils.auth import require_password

st.set_page_config(page_title="Trade Journal", page_icon="📓", layout="wide")
require_password()
st.title("📓 Trade Journal")

tab_log, tab_close, tab_history = st.tabs(["📥 Log new", "🏁 Close trade", "📚 History"])

with tab_log:
    with st.form("new_trade", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker").upper().strip()
        strategy = c2.selectbox(
            "Strategy",
            ["Long call", "Long put", "Short put", "Short call",
             "Vertical", "Iron condor", "Strangle", "Straddle",
             "Calendar", "Diagonal", "Covered call", "Other"],
        )
        qty = c3.number_input("Quantity", value=1.0, step=1.0)
        entry = st.number_input("Entry price (per contract)", value=0.0, step=0.05)
        thesis = st.text_area("Thesis", height=100,
                              placeholder="Why this trade? What's the edge?")
        submit = st.form_submit_button("Log trade")
        if submit:
            if not ticker:
                st.error("Ticker required.")
            else:
                tid = db.insert_trade(
                    ticker=ticker, strategy=strategy,
                    entry_price=entry, quantity=qty, thesis=thesis,
                )
                st.success(f"Logged trade #{tid}: {ticker} {strategy}")

with tab_close:
    open_df = db.open_trades()
    if open_df.empty:
        st.info("No open trades to close.")
    else:
        choice = st.selectbox(
            "Open trade",
            options=open_df["id"].tolist(),
            format_func=lambda i: (
                f"#{i} · "
                f"{open_df.loc[open_df['id']==i,'ticker'].iat[0]} "
                f"{open_df.loc[open_df['id']==i,'strategy'].iat[0]} "
                f"@ {open_df.loc[open_df['id']==i,'entry_price'].iat[0]}"
            ),
        )
        with st.form("close_trade"):
            row = open_df.loc[open_df["id"] == choice].iloc[0]
            entry = float(row["entry_price"] or 0)
            qty = float(row["quantity"] or 0)
            exit_p = st.number_input("Exit price (per contract)",
                                     value=entry, step=0.05)
            result = st.selectbox(
                "Result", ["win", "loss", "scratch"]
            )
            notes = st.text_area("Notes / lessons", height=100)
            submit = st.form_submit_button("Close trade")
            if submit:
                # Default contract multiplier: assume options 100x for $-PL.
                # Equity rows can be edited manually; this is a journal, not
                # a settlement system.
                pl = (exit_p - entry) * qty * 100
                db.close_trade(
                    int(choice), exit_price=exit_p, pl=pl,
                    result=result, notes=notes,
                )
                st.success(f"Closed #{choice}: P/L ${pl:,.2f}")
                st.rerun()

with tab_history:
    df = db.all_trades()
    if df.empty:
        st.info("No trades logged yet.")
    else:
        st.dataframe(df, use_container_width=True, height=600)
        st.download_button(
            "⬇️ Export CSV",
            data=df.to_csv(index=False),
            file_name=f"trades_{dt.date.today().isoformat()}.csv",
            mime="text/csv",
        )
