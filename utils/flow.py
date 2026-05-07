"""Unusual options flow scraper.

Barchart's unusual-activity page is partly gated. This best-effort scraper
hits the public HTML view and parses what's there. If Barchart changes their
markup or rate-limits, the panel will show a notice and an empty table.

For production use, swap in a paid feed (Cheddar Flow, FlowAlgo, BlackBoxStocks,
or Barchart's premium API).
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

BARCHART_URL = (
    "https://www.barchart.com/options/unusual-activity/stocks"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_unusual_flow() -> tuple[pd.DataFrame, str]:
    """Returns (df, source_note). df may be empty."""
    try:
        resp = requests.get(BARCHART_URL, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        return pd.DataFrame(), f"Request failed: {e}"

    if resp.status_code != 200:
        return (
            pd.DataFrame(),
            f"Barchart returned HTTP {resp.status_code} — likely rate-limited "
            "or behind a login. Consider a paid feed.",
        )

    soup = BeautifulSoup(resp.text, "lxml")
    # Barchart embeds JSON in inline data attributes; their public table renders
    # via JS so the static HTML rarely contains rows. Try a generic table parse.
    tables = soup.find_all("table")
    for tbl in tables:
        try:
            df = pd.read_html(str(tbl))[0]
            if {"Symbol", "Strike", "Exp Date"}.issubset(set(df.columns)):
                return _normalize(df), "Barchart (public HTML)"
        except (ValueError, IndexError):
            continue

    return (
        pd.DataFrame(),
        "Barchart's public page returned no parseable table (it is JS-rendered "
        "and login-gated). Plug in a paid options-flow feed in utils/flow.py "
        "to populate this panel.",
    )


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "Symbol": "ticker",
        "Strike": "strike",
        "Exp Date": "expiry",
        "Type": "direction",
        "Volume": "volume",
        "Open Int": "open_interest",
        "Last": "premium",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    keep = [c for c in [
        "ticker", "direction", "strike", "expiry", "premium",
        "volume", "open_interest"
    ] if c in df.columns]
    df = df[keep].copy()
    if "premium" in df:
        df["premium"] = df["premium"].apply(_to_money)
    return df


def _to_money(v) -> float:
    if pd.isna(v):
        return 0.0
    s = str(v).strip().replace("$", "").replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB])?$", s, re.I)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    num = float(m.group(1))
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1)
    return num * mult
