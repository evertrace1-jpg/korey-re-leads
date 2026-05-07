"""Backtester page — synthesize options P&L from historical underlying data.

Honest about limits: uses Black-Scholes-priced options from realized-vol IV proxy.
Good enough for directional strategy ranking; not for IV-arb / calendar / condor.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import auth
from backtest import data as bt_data
from backtest import engine as bt_engine
from backtest import strategies as bt_strats

st.set_page_config(page_title="Backtester · Trading Dashboard", page_icon="🧪", layout="wide")
auth.require_password()

# --- Page header
st.title("🧪 Strategy Backtester")
st.caption(
    "Synthesizes options P&L from historical underlying prices via Black-Scholes. "
    "Useful for ranking strategies and finding edge before risking real capital. "
    "Honest limits documented at the bottom of the page."
)

# --- Sidebar configuration
with st.sidebar:
    st.markdown("### Backtest setup")
    ticker = st.text_input("Ticker", "SPY").upper().strip()
    lookback_years = st.slider("Lookback (years)", 1.0, 5.0, 3.0, 0.5)
    bankroll = st.number_input("Starting bankroll ($)", min_value=500.0, value=5000.0, step=500.0)
    contracts = st.number_input("Contracts per trade", min_value=1, max_value=10, value=1, step=1)
    iv_mult = st.slider(
        "IV multiplier (vs realized vol)",
        min_value=1.0, max_value=1.5, value=1.2, step=0.05,
        help="Real IV typically prices 10-30% above realized vol. 1.2 is a reasonable default.",
    )
    strike_step = st.selectbox("Strike step ($)", [0.5, 1.0, 2.5, 5.0], index=1)

    st.markdown("---")
    st.markdown("### Strategy")
    strat_name = st.selectbox("Strategy", list(bt_strats.STRATEGY_REGISTRY.keys()))
    days_to_exp = st.slider("Days to expiration at entry", 7, 60, 30)

    if strat_name in ("Long call", "Long put", "Cash-secured put"):
        target_delta = st.slider("Target delta", 0.10, 0.50, 0.30, 0.05)
    if strat_name == "Bull call spread":
        long_otm = st.slider("Long-strike OTM %", -0.05, 0.10, 0.0, 0.01,
                             help="Negative = ITM. 0 = ATM. Positive = OTM.")
        short_otm = st.slider("Short-strike OTM %", 0.0, 0.20, 0.05, 0.01)

    profit_target = st.slider("Exit at +profit % of premium", 25, 200, 50, 25)
    stop_loss = st.slider("Stop loss at −% of premium", 25, 300, 100, 25)
    days_buffer = st.slider("Close N days before expiry", 0, 14, 1)

    st.markdown("---")
    st.markdown("### Entry signal")
    signal_kind = st.selectbox(
        "Trigger",
        ["Always (whenever no open position)",
         "Underlying dropped X% in N days",
         "Underlying rose X% in N days",
         "RSI(14) below threshold",
         "RSI(14) above threshold"],
    )
    if signal_kind.startswith("Underlying dropped"):
        sig_pct = st.slider("% drop", 1.0, 15.0, 3.0, 0.5)
        sig_n = st.slider("Over N days", 1, 30, 5)
    elif signal_kind.startswith("Underlying rose"):
        sig_pct = st.slider("% rise", 1.0, 15.0, 3.0, 0.5)
        sig_n = st.slider("Over N days", 1, 30, 5)
    elif "RSI" in signal_kind and "below" in signal_kind:
        sig_thr = st.slider("RSI threshold (oversold)", 10, 50, 30)
    elif "RSI" in signal_kind and "above" in signal_kind:
        sig_thr = st.slider("RSI threshold (overbought)", 50, 90, 70)

    cooldown = st.slider("Cooldown days between trades", 0, 14, 1)

    st.markdown("---")
    run_btn = st.button("▶ Run backtest", type="primary", use_container_width=True)

# --- Build the entry signal
def build_signal():
    if signal_kind.startswith("Always"):
        return bt_engine.entry_always
    if signal_kind.startswith("Underlying dropped"):
        return bt_engine.entry_dropped_pct_in_n_days(sig_pct, sig_n)
    if signal_kind.startswith("Underlying rose"):
        return bt_engine.entry_rose_pct_in_n_days(sig_pct, sig_n)
    if "RSI" in signal_kind and "below" in signal_kind:
        return bt_engine.entry_rsi_below(sig_thr)
    if "RSI" in signal_kind and "above" in signal_kind:
        return bt_engine.entry_rsi_above(sig_thr)
    return bt_engine.entry_always

# --- Run
if run_btn:
    with st.spinner(f"Loading {ticker} history ({lookback_years}y)..."):
        try:
            history = bt_data.get_history(ticker, lookback_years=lookback_years)
        except Exception as e:
            st.error(f"Failed to load history for {ticker}: {e}")
            st.stop()

    st.info(
        f"Loaded {len(history)} trading days for {ticker} "
        f"({history.index[0].date()} → {history.index[-1].date()})."
    )

    # Build strategy_kwargs
    strategy_builder = bt_strats.STRATEGY_REGISTRY[strat_name]
    strategy_kwargs = {
        "days_to_exp": days_to_exp,
        "profit_target_pct": float(profit_target),
        "stop_loss_pct": float(stop_loss),
        "hold_days_before_expiry": int(days_buffer),
    }
    if strat_name in ("Long call", "Long put", "Cash-secured put"):
        strategy_kwargs["target_delta"] = float(target_delta)
    if strat_name == "Bull call spread":
        strategy_kwargs["long_strike_otm_pct"] = float(long_otm)
        strategy_kwargs["short_strike_otm_pct"] = float(short_otm)

    config = bt_engine.BacktestConfig(
        ticker=ticker,
        starting_bankroll=float(bankroll),
        contracts_per_trade=int(contracts),
        iv_multiplier=float(iv_mult),
        strike_step=float(strike_step),
        cooldown_days_after_close=int(cooldown),
    )

    with st.spinner("Running backtest..."):
        result = bt_engine.run_backtest(
            history=history,
            strategy_builder=strategy_builder,
            strategy_kwargs=strategy_kwargs,
            entry_signal=build_signal(),
            config=config,
        )

    stats = result["stats"]
    trade_log = result["trade_log"]
    equity = result["equity_curve"]

    # --- Summary metrics
    st.markdown("## Results")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Final bankroll", f"${stats.final_bankroll:,.2f}",
              f"{stats.total_return_pct:+.1f}%")
    c2.metric("Trades", stats.n_trades, f"{stats.win_rate_pct:.0f}% win rate")
    c3.metric("Max drawdown", f"{stats.max_drawdown_pct:.1f}%")
    c4.metric("Sharpe (annual)", f"{stats.sharpe_annual:.2f}")
    c5.metric("Profit factor", f"{stats.profit_factor:.2f}")

    c6, c7, c8 = st.columns(3)
    c6.metric("Avg win", f"${stats.avg_win:,.2f}")
    c7.metric("Avg loss", f"${stats.avg_loss:,.2f}")
    c8.metric("vs. buy-and-hold underlying",
              f"{stats.alpha_pct:+.1f}%",
              f"BH: {stats.benchmark_return_pct:+.1f}%")

    # --- Equity curve vs buy-and-hold
    st.markdown("### Equity curve vs. buy-and-hold benchmark")
    bh_equity = (history["Close"] / history["Close"].iloc[0]) * float(bankroll)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values, name="Strategy",
        line=dict(color="#fb923c", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=bh_equity.index, y=bh_equity.values, name=f"Buy & hold {ticker}",
        line=dict(color="#94a3b8", width=1, dash="dot"),
    ))
    fig.add_hline(y=float(bankroll), line_dash="dash", line_color="#475569",
                  annotation_text="Starting bankroll")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#1e293b",
        height=400,
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis_title="$",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Trade log
    st.markdown("### Trade log")
    if trade_log:
        df = pd.DataFrame(trade_log)
        df_show = df[[
            "open_date", "close_date", "days_held", "open_spot", "close_spot",
            "pnl_dollars", "pnl_pct", "close_reason",
        ]].copy()
        df_show.columns = ["Open", "Close", "Held (d)", "Spot open", "Spot close",
                           "P&L $", "P&L %", "Reason"]
        df_show["P&L $"] = df_show["P&L $"].apply(lambda x: f"{x:+,.2f}")
        df_show["P&L %"] = df_show["P&L %"].apply(lambda x: f"{x:+.1f}%")
        df_show["Spot open"] = df_show["Spot open"].apply(lambda x: f"{x:.2f}")
        df_show["Spot close"] = df_show["Spot close"].apply(lambda x: f"{x:.2f}")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        # Download button
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download trade log (CSV)",
            data=csv,
            file_name=f"{ticker}_{strat_name.replace(' ', '_')}_backtest.csv",
            mime="text/csv",
        )
    else:
        st.warning("No trades were opened. Try a more permissive entry signal or longer lookback.")

# --- Honest caveats (always visible)
st.markdown("---")
with st.expander("⚠️ Read this before trusting the numbers", expanded=False):
    st.markdown("""
**What this backtester gets right (within ±20% accuracy):**
- Directional P&L on long calls / long puts at typical 0.30–0.50 deltas
- Bull/bear vertical spreads (because long and short legs share IV bias, errors mostly cancel)
- Cash-secured-put income strategies on liquid tickers (SPY, QQQ, large-cap)
- Relative ranking: "strategy A beats strategy B" is usually directionally correct

**What it gets wrong (numbers will be biased):**
- **IV crush** around earnings is not modeled. Long-straddle backtests will OVER-state P&L because real IV drops 30–50% post-earnings.
- **Volatility skew** isn't modeled. OTM puts cost more in real life than the BS price; short-put strategies will UNDER-state premium received.
- **Bid-ask spreads.** All trades use mid prices. Real fills are 5–15% worse, especially on weeklies and small-cap options.
- **Liquidity / slippage.** Backtest assumes you can always buy/sell at the model price. Real options on illiquid tickers don't trade at all sometimes.
- **Dividends and early exercise.** Not modeled. Matters for short calls on dividend payers (early assignment risk).
- **Iron condors, calendars, diagonals** require real historical IV — these strategies will mis-price systematically. Don't backtest them here.

**What to do with the results:**
1. Strategies with **negative alpha** vs. buy-and-hold over 3+ years probably have no real edge. Don't trade them.
2. Strategies with **positive alpha** in 1 backtest could be lucky — re-run on 3+ different tickers and 3+ different time windows to check robustness.
3. **Discount the results 20%** before deciding whether to live-trade. If a strategy needs the modeled return to be worth it, it's not worth it.
4. **Paper-trade the survivors** for 30+ days before risking real money. Paper P&L will catch the execution-friction issues backtests miss.
5. The journal panel is more important than the backtester. The backtester ranks ideas; the journal teaches you what *you* do well.
""")
