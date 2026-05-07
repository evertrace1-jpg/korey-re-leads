"""Earnings radar: pulls upcoming earnings + IV/move metrics from yfinance.

yfinance is free, slow, and rate-limited. The radar pulls a curated watchlist
rather than scanning the whole market — pass any list of tickers.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import streamlit as st
import yfinance as yf


DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
    "NFLX", "AVGO", "CRM", "ORCL", "ADBE", "QCOM", "INTC", "MU",
    "JPM", "BAC", "GS", "WFC",
    "XOM", "CVX",
    "WMT", "COST", "HD", "TGT",
    "UNH", "LLY", "PFE", "JNJ",
    "DIS", "NKE", "SBUX",
    "BA", "CAT", "GE",
    "UBER", "ABNB", "SHOP", "PLTR", "SOFI", "COIN",
]


@dataclass
class EarningsRow:
    ticker: str
    earnings_date: dt.date
    days_until: int
    iv_rank: float        # 0–100, computed from 52w IV proxy
    expected_move_pct: float
    last_move_pct: float  # last reported earnings 1-day move
    analyst_high: float
    analyst_low: float
    analyst_spread_pct: float

    @property
    def color(self) -> str:
        # Green: high IVR + tight analyst spread (clean setup)
        # Red: low IVR or wide spread (avoid)
        if self.iv_rank >= 60 and self.analyst_spread_pct <= 15:
            return "green"
        if self.iv_rank >= 40:
            return "yellow"
        return "red"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _iv_rank_proxy(hist: pd.DataFrame) -> float:
    """Realized-vol-rank proxy: where current 20d realized vol sits in the
    52w distribution. True IV rank needs option-IV history (not free)."""
    if hist is None or len(hist) < 60:
        return 0.0
    rets = hist["Close"].pct_change().dropna()
    rv20 = rets.rolling(20).std() * (252 ** 0.5) * 100
    rv20 = rv20.dropna()
    if rv20.empty:
        return 0.0
    cur = float(rv20.iloc[-1])
    lo, hi = float(rv20.min()), float(rv20.max())
    if hi - lo < 1e-9:
        return 0.0
    return round((cur - lo) / (hi - lo) * 100.0, 1)


def _expected_move_pct(hist: pd.DataFrame, days_to_earnings: int) -> float:
    if hist is None or len(hist) < 30 or days_to_earnings <= 0:
        return 0.0
    rets = hist["Close"].pct_change().dropna()
    daily_vol = float(rets.std())
    return round(daily_vol * (days_to_earnings ** 0.5) * 100.0, 2)


def _last_earnings_move_pct(ticker: yf.Ticker) -> float:
    try:
        edates = ticker.earnings_dates
        if edates is None or edates.empty:
            return 0.0
        past = edates[edates.index < pd.Timestamp.now(tz=edates.index.tz)]
        if past.empty:
            return 0.0
        last_date = past.index.max().tz_convert(None).normalize()
        # 2-day window around earnings to capture after-hours move
        start = last_date - pd.Timedelta(days=1)
        end = last_date + pd.Timedelta(days=3)
        hist = ticker.history(start=start, end=end, auto_adjust=False)
        if len(hist) < 2:
            return 0.0
        return round(
            (float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1.0)
            * 100.0,
            2,
        )
    except Exception:
        return 0.0


def _analyst_spread(ticker: yf.Ticker) -> tuple[float, float, float]:
    """Returns (high, low, spread_pct_of_current_price)."""
    try:
        info = ticker.info or {}
        hi = float(info.get("targetHighPrice") or 0)
        lo = float(info.get("targetLowPrice") or 0)
        cur = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        if cur > 0 and hi > 0 and lo > 0:
            return hi, lo, round((hi - lo) / cur * 100.0, 1)
    except Exception:
        pass
    return 0.0, 0.0, 0.0


@st.cache_data(ttl=60 * 60, show_spinner=False)
def scan_earnings(tickers: list[str], window_days: int = 60) -> pd.DataFrame:
    today = dt.date.today()
    horizon = today + dt.timedelta(days=window_days)
    rows: list[EarningsRow] = []

    for sym in tickers:
        t = yf.Ticker(sym)
        edates = _safe(lambda: t.earnings_dates)
        if edates is None or edates.empty:
            continue
        future = edates[edates.index >= pd.Timestamp.now(tz=edates.index.tz)]
        if future.empty:
            continue
        next_dt = future.index.min().tz_convert(None).date()
        if next_dt > horizon:
            continue
        days_until = (next_dt - today).days

        hist = _safe(lambda: t.history(period="1y", auto_adjust=False))
        ivr = _iv_rank_proxy(hist)
        em = _expected_move_pct(hist, max(days_until, 1))
        last_mv = _last_earnings_move_pct(t)
        hi, lo, spread = _analyst_spread(t)

        rows.append(
            EarningsRow(
                ticker=sym,
                earnings_date=next_dt,
                days_until=days_until,
                iv_rank=ivr,
                expected_move_pct=em,
                last_move_pct=last_mv,
                analyst_high=hi,
                analyst_low=lo,
                analyst_spread_pct=spread,
            )
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([r.__dict__ for r in rows])
    df["color"] = [r.color for r in rows]
    df = df.sort_values(["iv_rank", "days_until"], ascending=[False, True])
    return df.reset_index(drop=True)
