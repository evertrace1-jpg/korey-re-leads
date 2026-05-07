"""Strategy library: 5 canned options strategies the backtest engine can simulate.

Each strategy is a function returning a dict with:
  legs: list of {symbol_label, strike, is_call, action ('buy'|'sell'), entry_price}
  net_debit: float (positive = paid, negative = received credit)
  max_loss: float
  max_profit: float (or None for unlimited)
  exit_rules: dict {profit_target_pct, stop_loss_pct, hold_days_before_expiry}

The engine then walks forward day by day, marks the position to market using
black_scholes(), checks exit conditions, and records P&L on close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .pricing import black_scholes, estimate_iv_from_realized, find_strike_by_delta, round_strike


@dataclass
class Leg:
    label: str        # e.g., "long_call_30d"
    strike: float
    is_call: bool
    is_long: bool     # True = bought, False = sold
    entry_price: float


@dataclass
class Position:
    strategy_name: str
    open_date: str    # ISO date
    expiry_date: str  # ISO date
    days_to_exp_at_open: int
    legs: list[Leg]
    net_debit: float        # Positive = we paid; negative = we received credit
    max_loss: float         # Per contract, in $
    max_profit: Optional[float]  # None = unlimited (e.g., long call)
    exit_rules: dict = field(default_factory=dict)
    notes: str = ""


# ---- Strategy 1: long call (directional bullish) ----
def build_long_call(
    spot: float,
    realized_vol_pct: float,
    days_to_exp: int = 30,
    target_delta: float = 0.30,
    iv_multiplier: float = 1.2,
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 100.0,   # 100% = lose the entire premium
    hold_days_before_expiry: int = 1,
    open_date: str = "",
    expiry_date: str = "",
    strike_step: float = 1.0,
) -> Position:
    iv = estimate_iv_from_realized(realized_vol_pct, iv_multiplier)
    strike = find_strike_by_delta(spot, days_to_exp, iv, target_delta, is_call=True, strike_step=strike_step)
    price = black_scholes(spot, strike, days_to_exp, iv, is_call=True).price
    leg = Leg(label="long_call", strike=strike, is_call=True, is_long=True, entry_price=price)
    return Position(
        strategy_name=f"Long call ({int(target_delta*100)}Δ, {days_to_exp}DTE)",
        open_date=open_date,
        expiry_date=expiry_date,
        days_to_exp_at_open=days_to_exp,
        legs=[leg],
        net_debit=price,
        max_loss=price,         # premium paid
        max_profit=None,        # unlimited
        exit_rules={"profit_target_pct": profit_target_pct, "stop_loss_pct": stop_loss_pct,
                    "hold_days_before_expiry": hold_days_before_expiry},
    )


# ---- Strategy 2: long put (directional bearish) ----
def build_long_put(
    spot: float,
    realized_vol_pct: float,
    days_to_exp: int = 30,
    target_delta: float = 0.30,
    iv_multiplier: float = 1.2,
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 100.0,
    hold_days_before_expiry: int = 1,
    open_date: str = "",
    expiry_date: str = "",
    strike_step: float = 1.0,
) -> Position:
    iv = estimate_iv_from_realized(realized_vol_pct, iv_multiplier)
    strike = find_strike_by_delta(spot, days_to_exp, iv, target_delta, is_call=False, strike_step=strike_step)
    price = black_scholes(spot, strike, days_to_exp, iv, is_call=False).price
    leg = Leg(label="long_put", strike=strike, is_call=False, is_long=True, entry_price=price)
    return Position(
        strategy_name=f"Long put ({int(target_delta*100)}Δ, {days_to_exp}DTE)",
        open_date=open_date,
        expiry_date=expiry_date,
        days_to_exp_at_open=days_to_exp,
        legs=[leg],
        net_debit=price,
        max_loss=price,
        max_profit=strike - price,   # if underlying → 0, put worth ~strike
        exit_rules={"profit_target_pct": profit_target_pct, "stop_loss_pct": stop_loss_pct,
                    "hold_days_before_expiry": hold_days_before_expiry},
    )


# ---- Strategy 3: bull call spread (capped bullish) ----
def build_bull_call_spread(
    spot: float,
    realized_vol_pct: float,
    days_to_exp: int = 30,
    long_strike_otm_pct: float = 0.0,   # 0 = ATM long
    short_strike_otm_pct: float = 0.05,  # 5% OTM short
    iv_multiplier: float = 1.2,
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 100.0,
    hold_days_before_expiry: int = 1,
    open_date: str = "",
    expiry_date: str = "",
    strike_step: float = 1.0,
) -> Position:
    iv = estimate_iv_from_realized(realized_vol_pct, iv_multiplier)
    long_k = round_strike(spot, strike_step, long_strike_otm_pct, is_call=True)
    short_k = round_strike(spot, strike_step, short_strike_otm_pct, is_call=True)
    if short_k <= long_k:
        short_k = long_k + strike_step
    long_price = black_scholes(spot, long_k, days_to_exp, iv, is_call=True).price
    short_price = black_scholes(spot, short_k, days_to_exp, iv, is_call=True).price
    net_debit = long_price - short_price
    width = short_k - long_k
    return Position(
        strategy_name=f"Bull call spread ({long_k:.0f}/{short_k:.0f}, {days_to_exp}DTE)",
        open_date=open_date,
        expiry_date=expiry_date,
        days_to_exp_at_open=days_to_exp,
        legs=[
            Leg(label="long_call", strike=long_k, is_call=True, is_long=True, entry_price=long_price),
            Leg(label="short_call", strike=short_k, is_call=True, is_long=False, entry_price=short_price),
        ],
        net_debit=net_debit,
        max_loss=net_debit,
        max_profit=width - net_debit,
        exit_rules={"profit_target_pct": profit_target_pct, "stop_loss_pct": stop_loss_pct,
                    "hold_days_before_expiry": hold_days_before_expiry},
    )


# ---- Strategy 4: cash-secured put (income / get-paid-to-buy) ----
def build_cash_secured_put(
    spot: float,
    realized_vol_pct: float,
    days_to_exp: int = 30,
    target_delta: float = 0.30,    # sell a 30-delta put = ~30% prob ITM at expiry
    iv_multiplier: float = 1.2,
    profit_target_pct: float = 50.0,  # close when 50% of premium captured
    stop_loss_pct: float = 200.0,     # close if loss is 2× premium received
    hold_days_before_expiry: int = 7,
    open_date: str = "",
    expiry_date: str = "",
    strike_step: float = 1.0,
) -> Position:
    iv = estimate_iv_from_realized(realized_vol_pct, iv_multiplier)
    strike = find_strike_by_delta(spot, days_to_exp, iv, target_delta, is_call=False, strike_step=strike_step)
    price = black_scholes(spot, strike, days_to_exp, iv, is_call=False).price
    leg = Leg(label="short_put", strike=strike, is_call=False, is_long=False, entry_price=price)
    return Position(
        strategy_name=f"Cash-secured put ({int(target_delta*100)}Δ, {days_to_exp}DTE)",
        open_date=open_date,
        expiry_date=expiry_date,
        days_to_exp_at_open=days_to_exp,
        legs=[leg],
        net_debit=-price,            # we received premium
        max_loss=strike - price,     # if underlying → 0 (rare but real)
        max_profit=price,            # premium received
        exit_rules={"profit_target_pct": profit_target_pct, "stop_loss_pct": stop_loss_pct,
                    "hold_days_before_expiry": hold_days_before_expiry},
        notes="Requires (strike × 100) cash collateral per contract.",
    )


# ---- Strategy 5: long straddle (volatility / earnings play) ----
def build_long_straddle(
    spot: float,
    realized_vol_pct: float,
    days_to_exp: int = 14,
    iv_multiplier: float = 1.2,
    profit_target_pct: float = 75.0,
    stop_loss_pct: float = 50.0,
    hold_days_before_expiry: int = 0,
    open_date: str = "",
    expiry_date: str = "",
    strike_step: float = 1.0,
) -> Position:
    iv = estimate_iv_from_realized(realized_vol_pct, iv_multiplier)
    strike = round(spot / strike_step) * strike_step
    call_p = black_scholes(spot, strike, days_to_exp, iv, is_call=True).price
    put_p = black_scholes(spot, strike, days_to_exp, iv, is_call=False).price
    net = call_p + put_p
    return Position(
        strategy_name=f"Long straddle (ATM {strike:.0f}, {days_to_exp}DTE)",
        open_date=open_date,
        expiry_date=expiry_date,
        days_to_exp_at_open=days_to_exp,
        legs=[
            Leg(label="long_call", strike=strike, is_call=True, is_long=True, entry_price=call_p),
            Leg(label="long_put", strike=strike, is_call=False, is_long=True, entry_price=put_p),
        ],
        net_debit=net,
        max_loss=net,
        max_profit=None,           # unlimited on big moves either way
        exit_rules={"profit_target_pct": profit_target_pct, "stop_loss_pct": stop_loss_pct,
                    "hold_days_before_expiry": hold_days_before_expiry},
        notes="Bias warning: BS-based straddle backtest under-estimates IV-crush impact.",
    )


# ---- Position mark-to-market ----
def mark_position(pos: Position, spot: float, days_to_exp_now: int, current_iv: float, rate: float = 0.05) -> dict:
    """Compute current value of the position. Returns {value, pnl_dollars, pnl_pct}.

    value: net market value (long legs add, short legs subtract)
    pnl_dollars: per contract, in $ (positive = profitable)
    pnl_pct: relative to net_debit. For credit strategies (negative net_debit),
             pct is computed against the abs(credit) so it stays interpretable.
    """
    value = 0.0
    for leg in pos.legs:
        bs = black_scholes(spot, leg.strike, days_to_exp_now, current_iv, rate, leg.is_call)
        value += bs.price if leg.is_long else -bs.price
    # P&L = current value - net_debit (paid) for debit positions
    # For credit positions (net_debit < 0), P&L = -net_debit + value (since we received -net_debit upfront)
    pnl = value - pos.net_debit
    basis = abs(pos.net_debit) if pos.net_debit != 0 else 1.0
    pnl_pct = pnl / basis * 100.0
    return {"value": value, "pnl_dollars": pnl, "pnl_pct": pnl_pct}


# ---- Strategy registry for UI ----
STRATEGY_REGISTRY = {
    "Long call": build_long_call,
    "Long put": build_long_put,
    "Bull call spread": build_bull_call_spread,
    "Cash-secured put": build_cash_secured_put,
    "Long straddle": build_long_straddle,
}
