"""Historical price loader for the backtester. yfinance + Parquet disk cache.

Caches daily OHLCV per ticker so re-running backtests is fast (no re-fetching).
Cache invalidation: 24-hour TTL. Force refresh by deleting data/bt_cache/<ticker>.parquet.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "bt_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SEC = 24 * 3600


def get_history(ticker: str, lookback_years: float = 3.0) -> pd.DataFrame:
    """Returns daily OHLCV indexed by date (tz-naive). Cached on disk.

    Columns: Open, High, Low, Close, Volume, returns (log), realized_vol_30d (annualized %)
    """
    ticker = ticker.upper().strip()
    cache_file = CACHE_DIR / f"{ticker}.parquet"

    cache_fresh = (
        cache_file.exists()
        and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SEC
    )

    if cache_fresh:
        df = pd.read_parquet(cache_file)
    else:
        period = f"{int(lookback_years * 365)}d"
        df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if df.empty:
            raise ValueError(
                f"No price history returned for {ticker}. Check the ticker symbol."
            )
        # Strip timezone for stable downstream date math
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        # Add log returns + 30-day realized vol (annualized)
        import numpy as np
        df["returns"] = (df["Close"] / df["Close"].shift(1)).apply(
            lambda x: 0.0 if x is None or x <= 0 or pd.isna(x) else float(np.log(x))
        )
        df["realized_vol_30d"] = (
            df["returns"].rolling(30).std() * (252 ** 0.5) * 100
        )
        df.to_parquet(cache_file)

    # Slice to lookback window (cache may have more than requested)
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=int(lookback_years * 365))
    df = df[df.index >= cutoff].copy()
    return df


def cache_status() -> list[dict]:
    """List of dicts describing each cached ticker (for UI debug)."""
    out = []
    for f in CACHE_DIR.glob("*.parquet"):
        st = f.stat()
        age_hr = (time.time() - st.st_mtime) / 3600
        try:
            df = pd.read_parquet(f)
            rows = len(df)
            date_min = str(df.index.min().date())
            date_max = str(df.index.max().date())
        except Exception:
            rows, date_min, date_max = 0, "?", "?"
        out.append({
            "ticker": f.stem,
            "size_kb": round(st.st_size / 1024, 1),
            "rows": rows,
            "from": date_min,
            "to": date_max,
            "age_hours": round(age_hr, 1),
        })
    return out


def clear_cache(ticker: str | None = None) -> int:
    """Delete cached files. Returns # files removed."""
    n = 0
    if ticker:
        f = CACHE_DIR / f"{ticker.upper()}.parquet"
        if f.exists():
            f.unlink()
            n += 1
    else:
        for f in CACHE_DIR.glob("*.parquet"):
            f.unlink()
            n += 1
    return n
