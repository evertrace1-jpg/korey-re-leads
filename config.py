"""Loads .env config. Credentials live ONLY in .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "dashboard.db"

load_dotenv(ROOT / ".env")


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Missing {name} in .env. Edit {ROOT / '.env'} and restart."
        )
    return val


TASTYTRADE_USERNAME = _require("TASTYTRADE_USERNAME")
TASTYTRADE_PASSWORD = _require("TASTYTRADE_PASSWORD")
TASTYTRADE_ENV = os.getenv("TASTYTRADE_ENV", "paper").strip().lower()
IS_PAPER = TASTYTRADE_ENV != "live"

STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "5000"))
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "15"))
