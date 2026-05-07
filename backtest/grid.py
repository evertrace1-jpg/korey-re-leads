"""Parameter grid search for backtests. Used by the walk-forward validator.

Pattern:
    grid = {
        "target_delta": [0.20, 0.30, 0.40],
        "profit_target_pct": [25, 50, 100],
        "stop_loss_pct": [50, 100, 200],
    }
    results = run_grid(history, builder, base_kwargs, grid, signal, config)
    best = pick_best(results, by="alpha_pct")
"""
from __future__ import annotations

import itertools
from typing import Callable

import pandas as pd

from .engine import BacktestConfig, run_backtest


def expand_grid(grid: dict[str, list]) -> list[dict]:
    """Cartesian product of parameter values. {"a":[1,2], "b":[3]} → [{"a":1,"b":3},{"a":2,"b":3}]."""
    if not grid:
        return [{}]
    keys = list(grid.keys())
    value_lists = [grid[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*value_lists)]


def run_grid(
    history: pd.DataFrame,
    strategy_builder: Callable,
    base_kwargs: dict,
    param_grid: dict[str, list],
    entry_signal: Callable,
    config: BacktestConfig,
    progress_callback: Callable | None = None,
) -> list[dict]:
    """Run the backtest for every parameter combination. Returns sorted-by-input list of dicts:
        {params: {...}, alpha_pct, total_return_pct, sharpe, max_dd_pct, n_trades, win_rate_pct}
    """
    combos = expand_grid(param_grid)
    out = []
    for i, params in enumerate(combos):
        merged = {**base_kwargs, **params}
        try:
            r = run_backtest(
                history=history,
                strategy_builder=strategy_builder,
                strategy_kwargs=merged,
                entry_signal=entry_signal,
                config=config,
            )
            s = r["stats"]
            out.append({
                "params": params,
                "alpha_pct": s.alpha_pct,
                "total_return_pct": s.total_return_pct,
                "sharpe": s.sharpe_annual,
                "max_dd_pct": s.max_drawdown_pct,
                "n_trades": s.n_trades,
                "win_rate_pct": s.win_rate_pct,
                "profit_factor": s.profit_factor,
                "final_bankroll": s.final_bankroll,
            })
        except Exception as e:
            out.append({
                "params": params, "alpha_pct": -999.0, "total_return_pct": 0.0,
                "sharpe": 0.0, "max_dd_pct": 0.0, "n_trades": 0, "win_rate_pct": 0.0,
                "profit_factor": 0.0, "final_bankroll": config.starting_bankroll,
                "error": str(e),
            })
        if progress_callback:
            progress_callback(i + 1, len(combos))
    return out


def pick_best(grid_results: list[dict], by: str = "alpha_pct", min_trades: int = 3) -> dict | None:
    """Return the best parameter combination by the given metric.
    `min_trades` filters out combos that triggered too few trades to be meaningful.
    """
    eligible = [r for r in grid_results if r["n_trades"] >= min_trades and "error" not in r]
    if not eligible:
        # Fall back to whatever we have
        eligible = grid_results
    if not eligible:
        return None
    return max(eligible, key=lambda r: r.get(by, -999.0))
