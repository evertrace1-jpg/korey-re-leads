"""Thin wrapper around the tastytrade SDK (v9.x sync API).

Cached at module level so Streamlit reruns reuse the same Session.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import streamlit as st
from tastytrade import Account, Session
from tastytrade.instruments import get_option_chain

import config


@st.cache_resource(show_spinner="Connecting to Tastytrade…")
def get_session() -> Session:
    return Session(
        config.TASTYTRADE_USERNAME,
        config.TASTYTRADE_PASSWORD,
        is_test=config.IS_PAPER,
    )


@st.cache_resource(show_spinner=False)
def get_primary_account() -> Account:
    sess = get_session()
    accounts = Account.get_accounts(sess)
    if not accounts:
        raise RuntimeError("No accounts found on this Tastytrade login.")
    return accounts[0]


@dataclass
class PositionRow:
    symbol: str
    underlying: str
    instrument_type: str
    quantity: float
    direction: str
    avg_open_price: float
    mark: float
    multiplier: int
    cost_basis: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float


def _to_float(x: Any) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def fetch_positions() -> list[PositionRow]:
    sess = get_session()
    acct = get_primary_account()
    raw = acct.get_positions(sess)
    rows: list[PositionRow] = []
    for p in raw:
        qty = _to_float(getattr(p, "quantity", 0))
        direction = str(getattr(p, "quantity_direction", "") or "")
        signed_qty = qty if direction.lower() != "short" else -qty
        avg = _to_float(getattr(p, "average_open_price", 0))
        mark = _to_float(getattr(p, "mark_price", 0)) or _to_float(
            getattr(p, "close_price", 0)
        )
        mult = int(getattr(p, "multiplier", 1) or 1)
        cost = avg * abs(signed_qty) * mult
        mv = mark * signed_qty * mult
        # For short positions, P/L flips sign relative to market value
        pl = (mark - avg) * signed_qty * mult
        pct = (pl / cost * 100.0) if cost else 0.0
        rows.append(
            PositionRow(
                symbol=str(getattr(p, "symbol", "")),
                underlying=str(getattr(p, "underlying_symbol", "")),
                instrument_type=str(getattr(p, "instrument_type", "")),
                quantity=signed_qty,
                direction=direction,
                avg_open_price=avg,
                mark=mark,
                multiplier=mult,
                cost_basis=cost,
                market_value=mv,
                unrealized_pl=pl,
                unrealized_pl_pct=pct,
            )
        )
    return rows


def fetch_balances() -> dict[str, float]:
    sess = get_session()
    acct = get_primary_account()
    bal = acct.get_balances(sess)
    return {
        "cash_balance": _to_float(getattr(bal, "cash_balance", 0)),
        "net_liquidating_value": _to_float(
            getattr(bal, "net_liquidating_value", 0)
        ),
        "equity_buying_power": _to_float(
            getattr(bal, "equity_buying_power", 0)
        ),
        "derivative_buying_power": _to_float(
            getattr(bal, "derivative_buying_power", 0)
        ),
        "maintenance_requirement": _to_float(
            getattr(bal, "maintenance_requirement", 0)
        ),
    }


def fetch_option_chain(symbol: str) -> dict[dt.date, list[Any]]:
    """Returns {expiration_date: [Option, ...]}."""
    sess = get_session()
    return get_option_chain(sess, symbol.upper())


def account_label() -> str:
    acct = get_primary_account()
    env = "PAPER" if config.IS_PAPER else "LIVE"
    return f"{getattr(acct, 'account_number', '?')} · {env}"
