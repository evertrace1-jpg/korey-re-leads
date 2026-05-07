"""Black-Scholes pricing + IV estimation for backtester option-price synthesis.

Honest caveats:
- Real IV ≠ realized vol. The market typically prices IV at 1.1–1.3× realized.
  We use a configurable `iv_multiplier` (default 1.2) as a crude correction.
- IV crush around earnings is NOT modeled — so straddle/iron-condor backtests
  systematically over- or under-estimate P&L depending on direction.
- No skew modeling — OTM puts in real life cost more than OTM calls due to
  the volatility smile. Spread strategies dependent on skew will be biased.
- No bid-ask spread — we use fair-value mid prices. Real fills are worse,
  especially on illiquid strikes / weeklies. Subtract 5–15% from net P&L
  to ballpark execution friction.

For directional strategies (long calls/puts, vertical spreads) these limitations
are tolerable; the relative ranking of strategies is informative even if absolute
P&L is biased. For volatility-arbitrage strategies (calendars, condors) you need
real historical IV data — out of scope for the free tier.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ---- Standard normal CDF & PDF (no scipy dependency) ----
def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


# ---- Black-Scholes ----
@dataclass
class BSResult:
    price: float
    delta: float
    gamma: float
    vega: float          # per 1.00 absolute change in vol (i.e., per 100%)
    theta: float         # per year
    rho: float


def black_scholes(
    spot: float,
    strike: float,
    days_to_exp: float,
    iv: float,             # annualized, decimal (0.30 == 30%)
    rate: float = 0.05,    # risk-free rate, decimal
    is_call: bool = True,
) -> BSResult:
    """Standard Black-Scholes for European options on non-dividend-paying stock.

    Returns price + Greeks. Time in years (days/365). IV/rate as decimals.
    """
    if days_to_exp <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        # At/past expiration: intrinsic only
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
        return BSResult(
            price=intrinsic,
            delta=(1.0 if (is_call and spot > strike) else (-1.0 if (not is_call and spot < strike) else 0.0)),
            gamma=0.0,
            vega=0.0,
            theta=0.0,
            rho=0.0,
        )
    T = days_to_exp / 365.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    disc = math.exp(-rate * T)

    if is_call:
        price = spot * _cdf(d1) - strike * disc * _cdf(d2)
        delta = _cdf(d1)
        rho = strike * T * disc * _cdf(d2) / 100.0
    else:
        price = strike * disc * _cdf(-d2) - spot * _cdf(-d1)
        delta = _cdf(d1) - 1.0
        rho = -strike * T * disc * _cdf(-d2) / 100.0

    gamma = _pdf(d1) / (spot * iv * sqrt_T)
    vega = spot * _pdf(d1) * sqrt_T / 100.0  # per 1 vol point (i.e., per 1% vol move)
    theta_year = -(spot * _pdf(d1) * iv) / (2 * sqrt_T) - (
        rate * strike * disc * _cdf(d2) if is_call else -rate * strike * disc * _cdf(-d2)
    )
    theta = theta_year / 365.0  # per day

    return BSResult(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


# ---- IV estimation ----
def estimate_iv_from_realized(
    realized_vol_pct: float,
    iv_multiplier: float = 1.2,
    floor_pct: float = 8.0,
    ceiling_pct: float = 200.0,
) -> float:
    """Return decimal IV (e.g., 0.30 for 30%) from realized-vol % + multiplier.

    realized_vol_pct: 30-day realized vol, annualized, expressed as a percentage (e.g., 25.0)
    iv_multiplier: market typically prices IV at 1.1-1.3× realized; default 1.2.
    floor/ceiling: clamp to avoid degenerate cases on dead-quiet or extreme tickers.
    """
    if realized_vol_pct is None or realized_vol_pct <= 0:
        realized_vol_pct = 20.0  # safe-ish default
    iv_pct = max(floor_pct, min(ceiling_pct, realized_vol_pct * iv_multiplier))
    return iv_pct / 100.0


# ---- Strike selection helpers ----
def find_strike_by_delta(
    spot: float,
    days_to_exp: float,
    iv: float,
    target_delta: float,    # 0.30 means a 30-delta call (or -0.30 for put)
    is_call: bool = True,
    rate: float = 0.05,
    strike_step: float = 1.0,
) -> float:
    """Find the strike whose Black-Scholes delta is closest to target_delta.

    Searches across strikes in a ±50% range around spot. Useful for picking
    "0.30-delta calls" or "20-delta puts" — common strategy parameters.
    """
    target = abs(target_delta)
    lo = max(strike_step, spot * 0.5)
    hi = spot * 1.5
    # Round bounds to step
    lo = round(lo / strike_step) * strike_step
    hi = round(hi / strike_step) * strike_step

    best_strike = spot
    best_err = float("inf")
    k = lo
    while k <= hi:
        d = abs(black_scholes(spot, k, days_to_exp, iv, rate, is_call).delta)
        err = abs(d - target)
        if err < best_err:
            best_err = err
            best_strike = k
        k += strike_step
    return best_strike


def round_strike(spot: float, step: float = 1.0, otm_pct: float = 0.0, is_call: bool = True) -> float:
    """Pick a strike at spot ± otm_pct, rounded to the nearest step.
    Positive otm_pct moves OTM (above spot for calls, below for puts).
    """
    raw = spot * (1.0 + otm_pct) if is_call else spot * (1.0 - otm_pct)
    return round(raw / step) * step
