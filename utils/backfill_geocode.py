#!/usr/bin/env python3
"""One-time backfill: geocode existing re_leads rows and delete out-of-radius.

Run from project root:
    .venv/bin/python3 utils/backfill_geocode.py

Idempotent — re-running only re-geocodes rows that still have NULL lat/lng.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

# Make sibling imports work whether this is run as `python utils/backfill_geocode.py`
# or `python -m utils.backfill_geocode`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geocode import DEFAULT_MAX_MILES, geocode, miles_from_merrimack  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "dashboard.db")
MAX_MILES = float(os.environ.get("RE_LEADS_MAX_MILES", DEFAULT_MAX_MILES))

# city column is stored as "City, ST" — split on the LAST comma.
CITY_STATE_RE = re.compile(r"^(.+),\s*([A-Z]{2})\s*$")


def parse_city_state(s: str):
    if not s:
        return ("", "")
    s = s.strip()
    m = CITY_STATE_RE.match(s)
    if m:
        return (m.group(1).strip(), m.group(2).strip().upper())
    # Last-resort: split on last comma
    if "," in s:
        head, _, tail = s.rpartition(",")
        return (head.strip(), tail.strip().upper())
    return (s, "")


def ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(re_leads)")}
    for col, decl in (("lat", "REAL"), ("lng", "REAL"), ("dist_mi", "REAL")):
        if col not in existing:
            conn.execute(f"ALTER TABLE re_leads ADD COLUMN {col} {decl}")
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    rows = list(
        conn.execute(
            "SELECT id, city, lat, lng, dist_mi FROM re_leads ORDER BY id"
        ).fetchall()
    )
    total = len(rows)
    print(f"Backfilling {total} rows… (~1 sec per unique uncached city)")

    geocoded = 0
    failed = 0
    in_radius = 0
    out_radius = 0
    delete_ids = []

    for r in rows:
        rid = r["id"]
        if r["lat"] is not None and r["lng"] is not None and r["dist_mi"] is not None:
            # already done; just classify against current radius
            if r["dist_mi"] <= MAX_MILES:
                in_radius += 1
            else:
                out_radius += 1
                delete_ids.append(rid)
            continue

        city, state = parse_city_state(r["city"] or "")
        coords = geocode(city, state)
        if coords is None:
            failed += 1
            delete_ids.append(rid)  # conservative: drop unresolvable
            continue

        dist = miles_from_merrimack(*coords)
        conn.execute(
            "UPDATE re_leads SET lat=?, lng=?, dist_mi=? WHERE id=?",
            (coords[0], coords[1], round(dist, 2), rid),
        )
        geocoded += 1
        if dist <= MAX_MILES:
            in_radius += 1
        else:
            out_radius += 1
            delete_ids.append(rid)

    conn.commit()

    if delete_ids:
        conn.executemany(
            "DELETE FROM re_leads WHERE id=?", [(i,) for i in delete_ids]
        )
        conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM re_leads").fetchone()[0]

    print()
    print("=" * 50)
    print("BACKFILL SUMMARY")
    print("=" * 50)
    print(f"  Total rows scanned : {total}")
    print(f"  Newly geocoded     : {geocoded}")
    print(f"  Failed to geocode  : {failed}  (deleted)")
    print(f"  In radius (<= {MAX_MILES:.0f} mi): {in_radius}")
    print(f"  Out of radius      : {out_radius}  (deleted)")
    print(f"  Rows remaining     : {remaining}")

    conn.close()


if __name__ == "__main__":
    main()
