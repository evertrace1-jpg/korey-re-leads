"""Walk-forward validator — the cure for backtest overfitting.

Pattern:
    1. Split history at the X% mark (default 70%) → train + test
    2. Grid-search the parameter combinations on TRAIN; pick the winner
    3. Run that single best combination on TEST (data it never saw)
    4. Compare train alpha vs test alpha. Big gap = overfit.

A strategy that has +50% alpha on train and -10% alpha on test is not a strategy —
it's a curve fit to the train period. A strategy with +20% alpha on train and +15%
on test has likely captured something real.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import auth
from backtest import data as bt_data
from backtest import engine as bt_engine
from backtest import grid as bt_grid
from backtest import strategies as bt_strats
from backtest.metrics import compute_stats

st.set_page_config(page_title="Walk-Forward · Trading Dashboard", page_icon="🧬", layout="wide")
auth.require_password()

st.title("🧬 Walk-Forward Validator")
st.caption(
    "Splits historical data into train/test, optimizes parameters on train, then evaluates "
    "the winner on the held-out test data. Gap between train and test performance = overfit signal."
)

# --- Sidebar
with st.sidebar:
    st.markdown("### Setup")
    ticker = st.text_input("Ticker", "SPY").upper().strip()
    lookback_years = st.slider("Lookback (years)", 2.0, 5.0, 3.0, 0.5)
    bankroll = st.number_input("Starting bankroll ($)", min_value=500.0, value=5000.0, step=500.0)
    train_pct = st.slider("Train split %", 50, 80, 70, 5,
                          help="70% is standard. Higher = more train data, less out-of-sample test.")

    st.markdown("---")
    st.markdown("### Base strategy")
    strat_name = st.selectbox("Strategy", ["Long call", "Long put", "Bull call spread", "Cash-secured put"])
    days_to_exp_default = st.slider("Days to expiration (FIXED)", 7, 60, 30,
                                    help="Fixed at this value across all train combinations.")

    st.markdown("---")
    st.markdown("### Parameter grid (these are tuned on train)")
    delta_options = st.multiselect("Target deltas to try",
                                   [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45],
                                   default=[0.20, 0.30, 0.40])
    profit_options = st.multiselect("Profit targets % to try",
                                    [25, 50, 75, 100, 150, 200],
                                    default=[25, 50, 100])
    stop_options = st.multiselect("Stop losses % to try",
                                  [50, 75, 100, 150, 200, 300],
                                  default=[50, 100, 200])

    st.markdown("---")
    st.markdown("### Entry signal (FIXED across train)")
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

    iv_mult = st.slider("IV multiplier", 1.0, 1.5, 1.2, 0.05)
    days_buffer = st.slider("Close N days before expiry", 0, 14, 1)
    cooldown = st.slider("Cooldown days", 0, 14, 1)

    n_combos = max(1, len(delta_options)) * max(1, len(profit_options)) * max(1, len(stop_options))
    st.info(f"Grid size: **{n_combos} combinations** to test on train.")

    st.markdown("---")
    optimize_by = st.selectbox(
        "Pick winner by",
        ["alpha_pct", "sharpe", "total_return_pct", "profit_factor"],
        help="Metric used to choose the 'best' parameter set on train.",
    )
    min_trades = st.slider("Min trades to consider valid", 1, 20, 3,
                           help="Combos with fewer trades than this are excluded from 'best' selection.")
    run_btn = st.button("▶ Run walk-forward", type="primary", use_container_width=True)


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


if run_btn:
    if not delta_options or not profit_options or not stop_options:
        st.error("Pick at least one value for each parameter to grid-search.")
        st.stop()

    with st.spinner(f"Loading {ticker} ({lookback_years}y)..."):
        try:
            history = bt_data.get_history(ticker, lookback_years=lookback_years)
        except Exception as e:
            st.error(f"Failed: {e}")
            st.stop()

    n_total = len(history)
    split_idx = int(n_total * train_pct / 100)
    train_hist = history.iloc[:split_idx].copy()
    test_hist = history.iloc[split_idx:].copy()

    st.markdown(
        f"**Split:** {len(train_hist)} train days "
        f"({train_hist.index[0].date()} → {train_hist.index[-1].date()}) | "
        f"{len(test_hist)} test days "
        f"({test_hist.index[0].date()} → {test_hist.index[-1].date()})"
    )

    # Build the parameter grid
    param_grid = {
        "target_delta": delta_options if strat_name in ("Long call", "Long put", "Cash-secured put") else [0.30],
        "profit_target_pct": [float(p) for p in profit_options],
        "stop_loss_pct": [float(p) for p in stop_options],
    }
    base_kwargs = {
        "days_to_exp": days_to_exp_default,
        "hold_days_before_expiry": int(days_buffer),
    }
    config = bt_engine.BacktestConfig(
        ticker=ticker,
        starting_bankroll=float(bankroll),
        iv_multiplier=float(iv_mult),
        cooldown_days_after_close=int(cooldown),
    )
    builder = bt_strats.STRATEGY_REGISTRY[strat_name]
    signal = build_signal()

    # ========== TRAIN: grid search ==========
    st.markdown("## Step 1: train — grid search on first portion")
    progress = st.progress(0.0, text=f"Testing {n_combos} combinations on train...")
    def cb(done, total):
        progress.progress(done / total, text=f"Train combo {done}/{total}")

    train_results = bt_grid.run_grid(
        history=train_hist,
        strategy_builder=builder,
        base_kwargs=base_kwargs,
        param_grid=param_grid,
        entry_signal=signal,
        config=config,
        progress_callback=cb,
    )
    progress.empty()

    # Show top 10 from train
    train_df = pd.DataFrame([
        {**r["params"], **{k: v for k, v in r.items() if k not in ("params",)}} for r in train_results
    ])
    train_df_sorted = train_df.sort_values(optimize_by, ascending=False)
    st.markdown(f"#### Top 10 train combinations (by `{optimize_by}`)")
    st.dataframe(
        train_df_sorted.head(10).round(2),
        use_container_width=True, hide_index=True,
    )

    best = bt_grid.pick_best(train_results, by=optimize_by, min_trades=min_trades)
    if not best or best.get("alpha_pct", -999) == -999:
        st.error(f"No combination produced ≥{min_trades} trades on train. Loosen the entry signal or extend lookback.")
        st.stop()

    st.success(
        f"**Train winner:** "
        f"{best['params']} → alpha {best['alpha_pct']:+.1f}%, "
        f"Sharpe {best['sharpe']:.2f}, {best['n_trades']} trades, win rate {best['win_rate_pct']:.0f}%"
    )

    # ========== TEST: single run with the train winner ==========
    st.markdown("## Step 2: test — single run with train winner on held-out data")
    test_kwargs = {**base_kwargs, **best["params"]}
    test_result = bt_engine.run_backtest(
        history=test_hist,
        strategy_builder=builder,
        strategy_kwargs=test_kwargs,
        entry_signal=signal,
        config=config,
    )
    test_stats = test_result["stats"]

    # ========== Compare ==========
    st.markdown("## Verdict — train vs. test gap")
    c1, c2, c3 = st.columns(3)
    c1.metric("Train alpha", f"{best['alpha_pct']:+.1f}%")
    c2.metric("Test alpha", f"{test_stats.alpha_pct:+.1f}%")
    gap = best["alpha_pct"] - test_stats.alpha_pct
    c3.metric("Overfit gap", f"{gap:+.1f}%",
              delta_color="inverse",
              help="Train alpha − Test alpha. Large positive = overfit. Near zero or negative = robust.")

    c4, c5, c6 = st.columns(3)
    c4.metric("Train Sharpe", f"{best['sharpe']:.2f}")
    c5.metric("Test Sharpe", f"{test_stats.sharpe_annual:.2f}")
    c6.metric("Test trades", test_stats.n_trades)

    # Honest verdict
    if test_stats.n_trades < 3:
        st.warning(
            f"⚠️ Only {test_stats.n_trades} trades on test — too few to draw conclusions. "
            "Loosen the entry signal or extend lookback so test has more samples."
        )
    elif gap < 5 and test_stats.alpha_pct > 0:
        st.success(
            f"✅ **Robust.** Train and test alphas are close (gap {gap:+.1f}%) and test is positive. "
            "This strategy may have real edge. Paper-trade for 30+ days before live to verify "
            "execution friction matches your model assumptions."
        )
    elif gap < 15 and test_stats.alpha_pct > 0:
        st.info(
            f"🤔 **Plausible.** Some overfit (gap {gap:+.1f}%) but test still positive. "
            "Worth more validation — try different ticker (Batch Runner page) and "
            "different lookback windows before committing capital."
        )
    elif test_stats.alpha_pct > 0:
        st.warning(
            f"⚠️ **Heavily overfit.** Big train-test gap ({gap:+.1f}%), even though test is "
            "still positive. The 'tuned' parameters captured train-period noise. "
            "Try a smaller grid (fewer combos to overfit through) or a wider parameter range."
        )
    else:
        st.error(
            f"❌ **Failed out-of-sample.** Test alpha is negative ({test_stats.alpha_pct:+.1f}%) "
            "despite a positive train alpha ({best['alpha_pct']:+.1f}%). The strategy "
            "doesn't generalize. Don't trade it."
        )

    # Equity curve: train + test stitched
    st.markdown("### Equity curve — train (orange) into test (cyan)")
    train_eq = pd.Series([float(bankroll)] * len(train_hist), index=train_hist.index)
    # Re-run train with the BEST params to get its actual equity curve
    train_winner_run = bt_engine.run_backtest(
        history=train_hist,
        strategy_builder=builder,
        strategy_kwargs={**base_kwargs, **best["params"]},
        entry_signal=signal,
        config=config,
    )
    train_eq = train_winner_run["equity_curve"]
    test_eq = test_result["equity_curve"]

    # Stitch test equity to start where train ended
    if len(train_eq) > 0 and len(test_eq) > 0:
        test_eq_shifted = test_eq + (train_eq.iloc[-1] - test_eq.iloc[0])
    else:
        test_eq_shifted = test_eq

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=train_eq.index, y=train_eq.values, name="Train (in-sample)",
                             line=dict(color="#fb923c", width=2)))
    fig.add_trace(go.Scatter(x=test_eq_shifted.index, y=test_eq_shifted.values, name="Test (out-of-sample)",
                             line=dict(color="#22d3ee", width=2)))
    fig.add_vline(x=train_hist.index[-1], line_dash="dash", line_color="#94a3b8",
                  annotation_text="Train/test split")
    fig.add_hline(y=float(bankroll), line_dash="dot", line_color="#475569",
                  annotation_text="Starting bankroll")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#1e293b",
        height=400,
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Test trade log
    st.markdown("### Test-period trade log (out-of-sample, no parameter tuning)")
    if test_result["trade_log"]:
        df = pd.DataFrame(test_result["trade_log"])
        df_show = df[["open_date", "close_date", "days_held", "open_spot", "close_spot",
                      "pnl_dollars", "pnl_pct", "close_reason"]].copy()
        df_show.columns = ["Open", "Close", "Held(d)", "Spot open", "Spot close",
                           "P&L $", "P&L %", "Reason"]
        df_show["P&L $"] = df_show["P&L $"].apply(lambda x: f"{x:+,.2f}")
        df_show["P&L %"] = df_show["P&L %"].apply(lambda x: f"{x:+.1f}%")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

st.markdown("---")
with st.expander("Why walk-forward matters", expanded=False):
    st.markdown("""
**A backtest run on all your historical data has zero credibility.**

Here's why: with enough parameter combinations, you'll always find a combo that "worked"
on the data — by coincidence. That combo has zero predictive power for the future.

**Walk-forward fixes this** by holding out a portion of history that the parameter search
never sees. The strategy is forced to perform on data it didn't train on.

**The overfit gap** (train alpha minus test alpha) tells you how much of the apparent edge
is real and how much is curve-fit:
- Gap < 5%: the strategy generalizes. Promising.
- Gap 5-15%: some overfit, but test is still positive. Plausible.
- Gap > 15%: heavy overfit. Most "alpha" was data mining.
- Test negative: strategy doesn't work. Period.

**Interpretation pitfalls:**
- Tiny test sample (< 3 trades) → results aren't statistically meaningful, regardless of the numbers
- Test period is one regime (all bull, all bear) → you don't know if it works in the other
- You re-run the walk-forward 20 times tweaking sliders → you've just overfit at the meta-level
- "Best by Sharpe" can pick a low-trade-count combo with one big win → set min_trades ≥ 3

**The right workflow:**
1. Walk-forward on one ticker → if test passes, ...
2. Run the test-passing parameters on a different ticker (Batch Runner page) → if 3+ tickers pass, ...
3. Run on a different time window (set lookback further back) → if it still passes, ...
4. THEN paper-trade for 30+ days through the dashboard → if paper still works, ...
5. THEN live with smallest position size you can stand.

Skipping any step makes "overfitting" → "real money loss."
""")
