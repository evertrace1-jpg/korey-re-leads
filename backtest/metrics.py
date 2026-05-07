"""Performance metrics for completed backtests."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestStats:
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate_pct: float
    total_pnl: float
    total_return_pct: float          # vs. starting bankroll
    avg_win: float
    avg_loss: float
    profit_factor: float             # sum_wins / |sum_losses|
    max_drawdown_pct: float
    sharpe_annual: float             # daily-equity-curve Sharpe, annualized
    final_bankroll: float
    benchmark_return_pct: float      # buy-and-hold underlying over same window
    alpha_pct: float                 # backtest return minus benchmark


def compute_stats(
    trade_log: list[dict],
    equity_curve: pd.Series,
    starting_bankroll: float,
    benchmark_prices: pd.Series,
) -> BacktestStats:
    if not trade_log:
        return BacktestStats(
            n_trades=0, n_wins=0, n_losses=0, win_rate_pct=0.0,
            total_pnl=0.0, total_return_pct=0.0,
            avg_win=0.0, avg_loss=0.0, profit_factor=0.0,
            max_drawdown_pct=0.0, sharpe_annual=0.0,
            final_bankroll=starting_bankroll,
            benchmark_return_pct=0.0, alpha_pct=0.0,
        )

    pnls = [t["pnl_dollars"] for t in trade_log]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)

    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (
        float("inf") if wins else 0.0
    )

    # Max drawdown on the equity curve
    if len(equity_curve) > 1:
        running_max = equity_curve.cummax()
        drawdown_pct = ((equity_curve - running_max) / running_max).min() * 100
    else:
        drawdown_pct = 0.0

    # Daily Sharpe (annualized) on equity-curve daily returns
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) > 5 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)
    else:
        sharpe = 0.0

    # Benchmark: buy-and-hold underlying over the same window
    if len(benchmark_prices) >= 2:
        bench_ret = (benchmark_prices.iloc[-1] / benchmark_prices.iloc[0] - 1) * 100
    else:
        bench_ret = 0.0

    final_bk = starting_bankroll + total_pnl
    total_ret = (total_pnl / starting_bankroll) * 100 if starting_bankroll > 0 else 0.0

    return BacktestStats(
        n_trades=len(pnls),
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate_pct=len(wins) / len(pnls) * 100 if pnls else 0.0,
        total_pnl=total_pnl,
        total_return_pct=total_ret,
        avg_win=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        profit_factor=profit_factor if profit_factor != float("inf") else 999.0,
        max_drawdown_pct=float(drawdown_pct),
        sharpe_annual=float(sharpe),
        final_bankroll=final_bk,
        benchmark_return_pct=float(bench_ret),
        alpha_pct=total_ret - float(bench_ret),
    )
