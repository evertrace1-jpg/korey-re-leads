"""Batch runner — run the SAME strategy across N tickers, rank by alpha.

This is how you stress-test whether a strategy generalizes or only worked on one symbol.
A strategy that's positive-alpha on SPY but negative on QQQ + IWM + DIA is curve-fit, not edge.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import auth
from backtest import data as bt_data
from backtest import engine as bt_engine
from backtest import strategies as bt_strats

st.set_page_config(page_title="Batch Runner · Trading Dashboard", page_icon="📊", layout="wide")
auth.require_password()

st.title("📊 Multi-Ticker Batch Runner")
st.caption(
    "Run one strategy across many tickers in a single click. Rank by alpha vs. each "
    "ticker's buy-and-hold to find where the strategy actually has edge — and where it doesn't."
)

# --- Sidebar
with st.sidebar:
    st.markdown("### Tickers to test")
    tickers_text = st.text_area(
        "Tickers (one per line or comma-separated)",
        "SPY\nQQQ\nIWM\nDIA\nXLK\nXLF",
        height=180,
        help="Default 6 ETFs cover broad market + sector exposure. Mix in single names (AAPL, NVDA, etc.) to compare.",
    )
    tickers = [t.strip().upper() for t in tickers_text.replace(",", "\n").split("\n") if t.strip()]

    lookback_years = st.slider("Lookback (years)", 1.0, 5.0, 3.0, 0.5)
    bankroll = st.number_input("Starting bankroll per ticker ($)", min_value=500.0, value=5000.0, step=500.0)

    st.markdown("---")
    st.markdown("### Strategy (applied to ALL tickers)")
    strat_name = st.selectbox("Strategy", list(bt_strats.STRATEGY_REGISTRY.keys()))
    days_to_exp = st.slider("Days to expiration", 7, 60, 30)

    if strat_name in ("Long call", "Long put", "Cash-secured put"):
        target_delta = st.slider("Target delta", 0.10, 0.50, 0.30, 0.05)
    if strat_name == "Bull call spread":
        long_otm = st.slider("Long-strike OTM %", -0.05, 0.10, 0.0, 0.01)
        short_otm = st.slider("Short-strike OTM %", 0.0, 0.20, 0.05, 0.01)

    profit_target = st.slider("Profit target (% of premium)", 25, 200, 50, 25)
    stop_loss = st.slider("Stop loss (% of premium)", 25, 300, 100, 25)
    days_buffer = st.slider("Days-before-expiry close", 0, 14, 1)

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
    iv_mult = st.slider("IV multiplier", 1.0, 1.5, 1.2, 0.05)
    strike_step = st.selectbox("Strike step ($)", [0.5, 1.0, 2.5, 5.0], index=1)

    st.markdown("---")
    run_btn = st.button(f"▶ Run on {len(tickers)} tickers", type="primary", use_container_width=True)

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


if run_btn and tickers:
    # Build kwargs once; same for every ticker
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

    strategy_builder = bt_strats.STRATEGY_REGISTRY[strat_name]
    signal = build_signal()

    results = []
    equity_curves = {}
    progress = st.progress(0.0, text="Starting batch...")

    for idx, tkr in enumerate(tickers):
        progress.progress((idx + 0.05) / len(tickers), text=f"[{idx+1}/{len(tickers)}] Loading {tkr}...")
        try:
            history = bt_data.get_history(tkr, lookback_years=lookback_years)
        except Exception as e:
            results.append({
                "Ticker": tkr, "Trades": 0, "Win %": 0, "Return %": 0,
                "Alpha %": 0, "Sharpe": 0, "Max DD %": 0, "Final $": bankroll,
                "Status": f"❌ load failed: {e}",
            })
            continue

        progress.progress((idx + 0.5) / len(tickers), text=f"[{idx+1}/{len(tickers)}] Backtesting {tkr}...")
        config = bt_engine.BacktestConfig(
            ticker=tkr,
            starting_bankroll=float(bankroll),
            iv_multiplier=float(iv_mult),
            strike_step=float(strike_step),
            cooldown_days_after_close=int(cooldown),
        )
        try:
            result = bt_engine.run_backtest(
                history=history,
                strategy_builder=strategy_builder,
                strategy_kwargs=strategy_kwargs,
                entry_signal=signal,
                config=config,
            )
            s = result["stats"]
            results.append({
                "Ticker": tkr,
                "Trades": s.n_trades,
                "Win %": round(s.win_rate_pct, 1),
                "Return %": round(s.total_return_pct, 1),
                "Alpha %": round(s.alpha_pct, 1),
                "Sharpe": round(s.sharpe_annual, 2),
                "Max DD %": round(s.max_drawdown_pct, 1),
                "Final $": round(s.final_bankroll, 2),
                "BH %": round(s.benchmark_return_pct, 1),
                "Status": "✅" if s.n_trades > 0 else "⚠️ no trades",
            })
            # Normalize equity curve to starting bankroll = 100 so curves are comparable
            normed = result["equity_curve"] / float(bankroll) * 100.0
            equity_curves[tkr] = normed
        except Exception as e:
            results.append({
                "Ticker": tkr, "Trades": 0, "Win %": 0, "Return %": 0,
                "Alpha %": 0, "Sharpe": 0, "Max DD %": 0, "Final $": bankroll,
                "Status": f"❌ backtest failed: {e}",
            })

    progress.empty()

    # --- Display ranked
    st.markdown("## Results — ranked by alpha (descending)")
    df = pd.DataFrame(results)
    df_sorted = df.sort_values("Alpha %", ascending=False)
    st.dataframe(df_sorted, use_container_width=True, hide_index=True)

    # --- Aggregate summary
    valid = df_sorted[df_sorted["Trades"] > 0]
    if len(valid) > 0:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Mean alpha across tickers",
            f"{valid['Alpha %'].mean():+.1f}%",
            help="Mean of (strategy return − buy-hold return) across all tickers. Positive mean = strategy generalizes.",
        )
        c2.metric(
            "Tickers with positive alpha",
            f"{(valid['Alpha %'] > 0).sum()} / {len(valid)}",
        )
        c3.metric("Mean Sharpe", f"{valid['Sharpe'].mean():.2f}")
        c4.metric("Best ticker", valid.iloc[0]["Ticker"], f"{valid.iloc[0]['Alpha %']:+.1f}% alpha")

        # Honest interpretation
        pos_pct = (valid["Alpha %"] > 0).sum() / len(valid) * 100
        if pos_pct >= 70:
            st.success(
                f"**{pos_pct:.0f}% of tickers had positive alpha.** Strategy looks like real edge, "
                "not a curve-fit. Worth paper-trading the winners for 30+ days before going live."
            )
        elif pos_pct >= 40:
            st.warning(
                f"**Only {pos_pct:.0f}% of tickers had positive alpha.** Mixed result — strategy "
                "works in some regimes but not others. Investigate WHY: are the winners all in one "
                "sector? All small-cap? All low-IV? That's the actual edge."
            )
        else:
            st.error(
                f"**Only {pos_pct:.0f}% of tickers had positive alpha.** This strategy probably "
                "doesn't have generalizable edge. Either the parameters are wrong, or the entry "
                "signal is too coincidental. Re-tune or move on."
            )

    # --- Equity-curve overlay
    if equity_curves:
        st.markdown("### Equity curves (normalized to start = 100)")
        fig = go.Figure()
        for tkr, curve in equity_curves.items():
            fig.add_trace(go.Scatter(
                x=curve.index, y=curve.values, name=tkr,
                line=dict(width=1.5),
            ))
        fig.add_hline(y=100, line_dash="dot", line_color="#475569",
                      annotation_text="Start", annotation_position="bottom right")
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0f172a",
            plot_bgcolor="#1e293b",
            height=450,
            margin=dict(l=10, r=10, t=20, b=10),
            yaxis_title="Bankroll (start = 100)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- CSV export
    csv = df_sorted.to_csv(index=False)
    st.download_button(
        "📥 Download batch results (CSV)",
        data=csv,
        file_name=f"batch_{strat_name.replace(' ', '_')}_{len(tickers)}tickers.csv",
        mime="text/csv",
    )

st.markdown("---")
with st.expander("How to interpret these results", expanded=False):
    st.markdown("""
**The single most important number: % of tickers with positive alpha.**

A backtest on one ticker can be lucky (or unlucky). A strategy that beats buy-and-hold on
6 out of 6 unrelated tickers is much harder to dismiss as luck than a strategy that beats it on 1 out of 6.

**Look at the alpha distribution, not just the average.**
- Tight cluster of small positive alphas across all tickers → robust real edge
- One huge winner + 5 zeros → probably a single lucky regime, not a strategy
- Wide spread (some +50%, some -30%) → the strategy is exploiting something the tickers don't all have. Find what the winners share.

**Common patterns to watch for:**
- All winners are tech (XLK, NVDA, AAPL) → it's a beta-to-tech-momentum trade
- All winners are high-IV underlyings → it's a vol-premium harvest, will fail in low-vol regimes
- All winners are pre-earnings periods → it's an earnings vol play

The point of multi-ticker is to surface those patterns so you can name your edge. If you can't
explain in one sentence why your strategy works, you don't actually understand the edge — you've found
a coincidence.
""")
