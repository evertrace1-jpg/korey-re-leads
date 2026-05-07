"""SQLite layer for trade journal + bankroll snapshots."""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager

import pandas as pd

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at     TEXT NOT NULL,
    closed_at     TEXT,
    ticker        TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    entry_price   REAL,
    exit_price    REAL,
    quantity      REAL,
    pl            REAL,
    thesis        TEXT,
    result        TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS bankroll_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at    TEXT NOT NULL,
    nlv         REAL NOT NULL,
    cash        REAL,
    realized_pl REAL
);

CREATE TABLE IF NOT EXISTS re_leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    address     TEXT,
    city        TEXT,
    units       INTEGER,
    price       TEXT,
    status      TEXT,
    gross_rent  TEXT,
    owner_agent TEXT,
    phone       TEXT,
    email       TEXT,
    mls         TEXT,
    notes       TEXT,
    source      TEXT,
    date_added  TEXT,
    contacted   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
CREATE INDEX IF NOT EXISTS idx_snap_taken ON bankroll_snapshots(taken_at);
CREATE INDEX IF NOT EXISTS idx_re_leads_status ON re_leads(status);
"""


_RE_LEADS_SEED = [
    {
        "address": "38 Washington St",
        "city": "Claremont",
        "units": 3,
        "price": "$360,000",
        "status": "active",
        "gross_rent": "fully rented",
        "owner_agent": "Experience Homes Group",
        "phone": "",
        "email": "",
        "mls": "5070330",
        "notes": "Best value pick — ~$18K down at 5%, est. $350/mo net out of pocket.",
        "source": "MLS",
    },
    {
        "address": "19 Sanders St",
        "city": "Concord (Penacook)",
        "units": 3,
        "price": "$525,000",
        "status": "active",
        "gross_rent": "tenants pay utilities",
        "owner_agent": "",
        "phone": "",
        "email": "",
        "mls": "5083378",
        "notes": "Detached 2-car garage, I-93 access. Worth $490K offer.",
        "source": "MLS",
    },
    {
        "address": "157 Rumford St",
        "city": "Concord",
        "units": 3,
        "price": "$550,000",
        "status": "active",
        "gross_rent": "month-to-month tenants",
        "owner_agent": "",
        "phone": "",
        "email": "",
        "mls": "5068434",
        "notes": "Listed since Nov 2025 (6+ months on market = seller motivated).",
        "source": "MLS",
    },
    {
        "address": "Manchester East Side",
        "city": "Manchester",
        "units": 3,
        "price": "$530,000",
        "status": "watch",
        "gross_rent": "$6,700/mo ($2,350 + $2,200 + $2,150)",
        "owner_agent": "",
        "phone": "",
        "email": "",
        "mls": "",
        "notes": "Best rental income of the batch.",
        "source": "research",
    },
    {
        "address": "32 Mill St",
        "city": "Rochester",
        "units": None,
        "price": "$899,000",
        "status": "watch",
        "gross_rent": "",
        "owner_agent": "",
        "phone": "",
        "email": "",
        "mls": "",
        "notes": "First sale in 45 years — motivated seller, explore creative / seller financing.",
        "source": "research",
    },
]


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
    seed_re_leads()


def seed_re_leads() -> None:
    """Insert the starter NH multifamily leads on first run."""
    with conn() as c:
        existing = c.execute("SELECT COUNT(*) FROM re_leads").fetchone()[0]
        if existing:
            return
        today = dt.date.today().isoformat()
        c.executemany(
            """INSERT INTO re_leads(address, city, units, price, status,
                                    gross_rent, owner_agent, phone, email,
                                    mls, notes, source, date_added)
               VALUES (:address, :city, :units, :price, :status,
                       :gross_rent, :owner_agent, :phone, :email,
                       :mls, :notes, :source, :date_added)""",
            [{**lead, "date_added": today} for lead in _RE_LEADS_SEED],
        )


def get_re_leads(
    status_filter: str | None = None,
    hide_contacted: bool = False,
) -> list[dict]:
    sql = "SELECT * FROM re_leads"
    where: list[str] = []
    params: list = []
    if status_filter and status_filter.lower() != "all":
        where.append("LOWER(status) = ?")
        params.append(status_filter.lower())
    if hide_contacted:
        where.append("contacted = 0")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY contacted ASC, id ASC"
    with conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def add_re_lead(
    *,
    address: str,
    city: str,
    units: int | None,
    price: str,
    status: str,
    gross_rent: str = "",
    owner_agent: str = "",
    phone: str = "",
    email: str = "",
    mls: str = "",
    notes: str = "",
    source: str = "manual",
) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO re_leads(address, city, units, price, status,
                                    gross_rent, owner_agent, phone, email,
                                    mls, notes, source, date_added)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (address, city, units, price, status, gross_rent, owner_agent,
             phone, email, mls, notes, source, dt.date.today().isoformat()),
        )
        return int(cur.lastrowid)


def mark_contacted(lead_id: int, contacted: bool = True) -> None:
    with conn() as c:
        c.execute(
            "UPDATE re_leads SET contacted = ? WHERE id = ?",
            (1 if contacted else 0, lead_id),
        )


def insert_trade(
    *,
    ticker: str,
    strategy: str,
    entry_price: float | None,
    quantity: float | None,
    thesis: str,
    opened_at: dt.datetime | None = None,
) -> int:
    opened_at = opened_at or dt.datetime.now()
    with conn() as c:
        cur = c.execute(
            """INSERT INTO trades(opened_at, ticker, strategy, entry_price,
                                  quantity, thesis)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (opened_at.isoformat(), ticker.upper(), strategy,
             entry_price, quantity, thesis),
        )
        return int(cur.lastrowid)


def close_trade(
    trade_id: int,
    *,
    exit_price: float,
    pl: float,
    result: str,
    notes: str = "",
    closed_at: dt.datetime | None = None,
) -> None:
    closed_at = closed_at or dt.datetime.now()
    with conn() as c:
        c.execute(
            """UPDATE trades SET closed_at=?, exit_price=?, pl=?,
                                  result=?, notes=?
               WHERE id=?""",
            (closed_at.isoformat(), exit_price, pl, result, notes, trade_id),
        )


def all_trades() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(
            "SELECT * FROM trades ORDER BY opened_at DESC", c
        )


def open_trades() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(
            "SELECT * FROM trades WHERE closed_at IS NULL ORDER BY opened_at DESC",
            c,
        )


def record_snapshot(nlv: float, cash: float, realized_pl: float = 0.0) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO bankroll_snapshots(taken_at, nlv, cash, realized_pl)
               VALUES (?, ?, ?, ?)""",
            (dt.datetime.now().isoformat(), nlv, cash, realized_pl),
        )


def equity_curve() -> pd.DataFrame:
    with conn() as c:
        df = pd.read_sql_query(
            "SELECT taken_at, nlv, cash, realized_pl FROM bankroll_snapshots "
            "ORDER BY taken_at",
            c,
        )
    if not df.empty:
        df["taken_at"] = pd.to_datetime(df["taken_at"])
    return df
