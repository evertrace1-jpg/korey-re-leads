"""Main backtest engine: walks history day by day, opens/closes positions per signals.

Trade lifecycle:
  1. Each day, evaluate entry_signal(price_history_so_far) → True/False
  2. If True AND no open position: open a new position with the chosen strategy
  3. Each day with an open position: mark to market, check exit rules:
       - profit_target_pct hit → close
       - stop_loss_pct hit → close
       - days remaining ≤ hold_days_before_expiry → close
  4. On close: book P&L, log trade, equity curve updates

Position sizing: 1 contract per trade by default. Configurable.
Bankroll math: option contracts have multiplier 100 (each P&L unit × 100).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .pricing import estimate_iv_from_realized
from .strategies import Position, mark_position
from .metrics import compute_stats, BacktestStats

OPTION_MULTIPLIER = 100  # each contract = 100 underlying shares


@dataclass
class BacktestConfig:
    ticker: str
    starting_bankroll: float = 5000.0
    contracts_per_trade: int = 1
    iv_multiplier: float = 1.2
    rate: float = 0.05
    strike_step: float = 1.0
    cooldown_days_after_close: int = 1     # don't immediately re-open same day
    max_concurrent_positions: int = 1


# ---- Built-in entry signals ----
def entry_always(_history_so_far: pd.DataFrame) -> bool:
    """Always-on signal: open a new position the moment the previous closes (after cooldown)."""
    return True


def entry_dropped_pct_in_n_days(pct: float, days: int) -> Callable:
    """Returns a signal: True if Close has fallen ≥ pct% over the last `days`."""
    def f(hist: pd.DataFrame) -> bool:
        if len(hist) < days + 1:
            return False
        recent = hist["Close"].iloc[-days - 1 :]
        return (recent.iloc[-1] / recent.iloc[0] - 1) * 100 <= -pct
    return f


def entry_rose_pct_in_n_days(pct: float, days: int) -> Callable:
    def f(hist: pd.DataFrame) -> bool:
        if len(hist) < days + 1:
            return False
        recent = hist["Close"].iloc[-days - 1 :]
        return (recent.iloc[-1] / recent.iloc[0] - 1) * 100 >= pct
    return f


def entry_rsi_below(threshold: float, period: int = 14) -> Callable:
    def f(hist: pd.DataFrame) -> bool:
        if len(hist) < period + 1:
            return False
        delta = hist["Close"].diff()
        up = delta.clip(lower=0).rolling(period).mean()
        down = -delta.clip(upper=0).rolling(period).mean()
        rs = up / down.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        last = rsi.iloc[-1]
        return not pd.isna(last) and last < threshold
    return f


def entry_rsi_above(threshold: float, period: int = 14) -> Callable:
    def f(hist: pd.DataFrame) -> bool:
        if len(hist) < period + 1:
            return False
        delta = hist["Close"].diff()
        up = delta.clip(lower=0).rolling(period).mean()
        down = -delta.clip(upper=0).rolling(period).mean()
        rs = up / down.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        last = rsi.iloc[-1]
        return not pd.isna(last) and last > threshold
    return f


# ---- Engine ----
def run_backtest(
    history: pd.DataFrame,
    strategy_builder: Callable,
    strategy_kwargs: dict,
    entry_signal: Callable[[pd.DataFrame], bool],
    config: BacktestConfig,
) -> dict:
    """Run a single-strategy backtest.

    history: DataFrame from data.get_history() with Close + realized_vol_30d columns
    strategy_builder: a function from strategies.py (e.g., build_long_call)
    strategy_kwargs: extra kwargs for the builder (DTE, deltas, exits, etc.)
    entry_signal: callable taking history-up-to-day, returns True if open new pos
    config: BacktestConfig

    Returns dict:
      trade_log: list of dicts, one per closed trade
      equity_curve: pd.Series indexed by date, values in $
      stats: BacktestStats
    """
    open_pos: Optional[Position] = None
    open_idx: int = -1
    cooldown_until_idx: int = -1

    trade_log: list[dict] = []
    bankroll = config.starting_bankroll
    equity_per_day: list[tuple[pd.Timestamp, float]] = []

    days_to_exp_at_open = strategy_kwargs.get("days_to_exp", 30)
    hold_buffer = 1  # need at least this many days of price history to open

    for i in range(len(history)):
        today = history.index[i]
        spot_today = float(history["Close"].iloc[i])
        rv = float(history["realized_vol_30d"].iloc[i]) if not pd.isna(history["realized_vol_30d"].iloc[i]) else 20.0
        iv_today = estimate_iv_from_realized(rv, config.iv_multiplier)

        # ----- mark + maybe close existing position -----
        if open_pos is not None:
            days_held = (today - history.index[open_idx]).days
            days_to_exp_now = max(0, open_pos.days_to_exp_at_open - days_held)
            mark = mark_position(open_pos, spot_today, days_to_exp_now, iv_today, config.rate)

            should_close = False
            close_reason = ""
            er = open_pos.exit_rules
            # 1) Profit target
            if er.get("profit_target_pct") is not None and mark["pnl_pct"] >= er["profit_target_pct"]:
                should_close, close_reason = True, "profit_target"
            # 2) Stop loss
            elif er.get("stop_loss_pct") is not None and mark["pnl_pct"] <= -er["stop_loss_pct"]:
                should_close, close_reason = True, "stop_loss"
            # 3) Days-before-expiry forced close
            elif days_to_exp_now <= er.get("hold_days_before_expiry", 1):
                should_close, close_reason = True, "near_expiry"

            if should_close:
                pnl_per_contract = mark["pnl_dollars"]
                pnl_total = pnl_per_contract * config.contracts_per_trade * OPTION_MULTIPLIER
                bankroll += pnl_total
                trade_log.append({
                    "open_date": open_pos.open_date,
                    "close_date": today.isoformat()[:10],
                    "strategy": open_pos.strategy_name,
                    "days_held": days_held,
                    "open_spot": float(history["Close"].iloc[open_idx]),
                    "close_spot": spot_today,
                    "net_debit_per_contract": open_pos.net_debit,
                    "close_value_per_contract": mark["value"],
                    "pnl_dollars": pnl_total,
                    "pnl_pct": mark["pnl_pct"],
                    "close_reason": close_reason,
                })
                open_pos = None
                open_idx = -1
                cooldown_until_idx = i + config.cooldown_days_after_close

        # ----- maybe open new position -----
        if open_pos is None and i >= cooldown_until_idx and i >= hold_buffer:
            if entry_signal(history.iloc[: i + 1]):
                expiry_date = (today + pd.Timedelta(days=days_to_exp_at_open)).isoformat()[:10]
                kwargs_with_dates = {
                    **strategy_kwargs,
                    "spot": spot_today,
                    "realized_vol_pct": rv,
                    "iv_multiplier": config.iv_multiplier,
                    "open_date": today.isoformat()[:10],
                    "expiry_date": expiry_date,
                    "strike_step": config.strike_step,
                }
                # Remove keys the builder doesn't accept
                builder_safe_kwargs = {
                    k: v for k, v in kwargs_with_dates.items()
                    if k in strategy_builder.__code__.co_varnames
                }
                try:
                    open_pos = strategy_builder(**builder_safe_kwargs)
                    open_idx = i
                except Exception as e:
                    # Skip days where strategy can't be built (e.g., spot too low)
                    pass

        equity_per_day.append((today, bankroll))

    # If still open at end of history, mark to market and force-close
    if open_pos is not None and open_idx >= 0:
        spot = float(history["Close"].iloc[-1])
        rv = float(history["realized_vol_30d"].iloc[-1]) if not pd.isna(history["realized_vol_30d"].iloc[-1]) else 20.0
        iv = estimate_iv_from_realized(rv, config.iv_multiplier)
        days_held = (history.index[-1] - history.index[open_idx]).days
        days_to_exp_now = max(0, open_pos.days_to_exp_at_open - days_held)
        mark = mark_position(open_pos, spot, days_to_exp_now, iv, config.rate)
        pnl_total = mark["pnl_dollars"] * config.contracts_per_trade * OPTION_MULTIPLIER
        bankroll += pnl_total
        trade_log.append({
            "open_date": open_pos.open_date,
            "close_date": history.index[-1].isoformat()[:10],
            "strategy": open_pos.strategy_name,
            "days_held": days_held,
            "open_spot": float(history["Close"].iloc[open_idx]),
            "close_spot": spot,
            "net_debit_per_contract": open_pos.net_debit,
            "close_value_per_contract": mark["value"],
            "pnl_dollars": pnl_total,
            "pnl_pct": mark["pnl_pct"],
            "close_reason": "end_of_backtest",
        })

    # Build equity curve series
    equity_series = pd.Series(
        [v for _, v in equity_per_day],
        index=[d for d, _ in equity_per_day],
        name="bankroll",
    )

    stats = compute_stats(
        trade_log=trade_log,
        equity_curve=equity_series,
        starting_bankroll=config.starting_bankroll,
        benchmark_prices=history["Close"],
    )

    return {
        "trade_log": trade_log,
        "equity_curve": equity_series,
        "stats": stats,
        "config": asdict(config),
    }
