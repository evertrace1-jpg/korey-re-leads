#!/usr/bin/env python3
"""Multi-source NH/VT/ME multifamily property scraper.

Sources:
  - Craigslist (HTML search, real-estate by owner, all 3 states)
  - Redfin (HTML state-page multifamily filter, paginated)
  - Zillow (HTML search, multi-family per state)

Writes to data/dashboard.db re_leads table and regenerates static/leads.json.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from geocode import (
    DEFAULT_MAX_MILES,
    MERRIMACK_NH,
    geocode,
    miles_from_merrimack,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "dashboard.db")
LEADS_JSON = os.path.join(ROOT, "static", "leads.json")

# Drive-time radius from Merrimack, NH (~90 min by I-89/I-93/I-95).
MAX_MILES = float(os.environ.get("RE_LEADS_MAX_MILES", DEFAULT_MAX_MILES))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

CL_URLS = [
    ("https://nh.craigslist.org/search/reo", "NH"),
    ("https://vermont.craigslist.org/search/reo", "VT"),
    ("https://maine.craigslist.org/search/reo", "ME"),
]
RF_STATES = [("New-Hampshire", "NH"), ("Vermont", "VT"), ("Maine", "ME")]
Z_URLS = [
    ("https://www.zillow.com/nh/multi-family/", "NH"),
    ("https://www.zillow.com/vt/multi-family/", "VT"),
    ("https://www.zillow.com/me/multi-family/", "ME"),
]

MULTI_KEYWORDS = re.compile(
    r"\b(duplex|triplex|fourplex|quadplex|multi[-\s]?family|"
    r"\d+[\s-]?(?:unit|family|plex)|"
    r"(?:two|three|four)[-\s]?(?:unit|family))s?\b",
    re.I,
)
UNIT_NUM = re.compile(r"\b(\d+)[\s-]?(?:unit|family|plex)\b", re.I)
RENT_BASELINE = 1100  # $/unit/month


def detect_units(text: str) -> int | None:
    if not text:
        return None
    t = text.lower()
    m = UNIT_NUM.search(t)
    if m:
        n = int(m.group(1))
        if 2 <= n <= 12:
            return n
    if re.search(r"\bduplex|two[-\s]?family|2[-\s]?family\b", t):
        return 2
    if re.search(r"\btriplex|three[-\s]?family|3[-\s]?family\b", t):
        return 3
    if re.search(r"\bfourplex|quadplex|four[-\s]?family|4[-\s]?family\b", t):
        return 4
    if re.search(r"\bmulti[-\s]?family\b", t):
        return 3
    return None


def is_multi(text: str) -> bool:
    return bool(MULTI_KEYWORDS.search(text or ""))


def clean(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def parse_price(s) -> str:
    if s is None or s == "":
        return ""
    s = str(s)
    m = re.search(r"\$?([\d,]+(?:\.\d+)?)", s)
    if not m:
        return ""
    try:
        n = float(m.group(1).replace(",", ""))
        if n < 1:
            return ""
        return f"${int(n):,}"
    except Exception:
        return ""


def gross_rent(units: int | None) -> str:
    if not units:
        return ""
    return f"${units * RENT_BASELINE:,}"


def http_get(url: str, headers=None, timeout=25):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    return requests.get(url, headers=h, timeout=timeout)


# --------- Craigslist HTML ---------
def fetch_craigslist():
    rows = []
    errors = []
    for url, state in CL_URLS:
        try:
            r = http_get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.find_all("li", class_="cl-static-search-result")
            for li in items:
                title = clean(li.get("title") or "")
                a = li.find("a")
                href = a.get("href") if a else ""
                price_el = li.find(class_="price")
                loc_el = li.find(class_="location")
                price = parse_price(price_el.get_text() if price_el else "")
                city = clean(loc_el.get_text() if loc_el else "")
                if not is_multi(title):
                    continue
                units = detect_units(title) or 2
                rows.append({
                    "address": title[:120],
                    "city": city,
                    "state": state,
                    "units": units,
                    "price": price,
                    "url": href,
                    "notes": title,
                    "source": "Craigslist",
                })
            time.sleep(1)
        except Exception as ex:
            errors.append(f"Craigslist {state}: {ex}")
    return rows, errors


# --------- Redfin HTML state pages ---------
def parse_redfin_card(card, state_code: str):
    # card is the bp-Homecard__Content div; sibling/parent has the address link
    container = card.parent
    if not container:
        return None
    addr_a = container.find("a", class_=re.compile("bp-Homecard__Address"))
    if not addr_a:
        return None
    addr_text = clean(addr_a.get_text(" "))
    # "414 Fremont Rd, Chester, NH 03036"
    m = re.match(r"^(.*?),\s*([^,]+?),\s*([A-Z]{2})\s*(\d{5})?$", addr_text)
    if m:
        street, city, st, _zip = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    else:
        street, city, st = addr_text, "", state_code
    if st.upper() == "MA":
        return None
    href = addr_a.get("href") or ""
    if href.startswith("/"):
        href = "https://www.redfin.com" + href
    price_el = card.find(class_=re.compile("bp-Homecard__Price--value"))
    price = parse_price(price_el.get_text() if price_el else "")
    beds_el = card.find(class_=re.compile("bp-Homecard__Stats--beds"))
    baths_el = card.find(class_=re.compile("bp-Homecard__Stats--baths"))
    sqft_el = card.find(class_=re.compile("bp-Homecard__Stats--sqft"))
    beds_txt = clean(beds_el.get_text(" ") if beds_el else "")
    baths_txt = clean(baths_el.get_text(" ") if baths_el else "")
    sqft_txt = clean(sqft_el.get_text(" ") if sqft_el else "")
    beds_n = 0
    bm = re.search(r"\d+", beds_txt)
    if bm:
        beds_n = int(bm.group(0))
    if beds_n >= 8:
        units = 4
    elif beds_n >= 6:
        units = 3
    elif beds_n >= 4:
        units = 2
    else:
        units = 2
    return {
        "address": street,
        "city": city,
        "state": st,
        "units": units,
        "price": price,
        "url": href,
        "notes": f"{beds_txt} / {baths_txt} / {sqft_txt}".strip(" /"),
        "source": "Redfin",
    }


def fetch_redfin():
    rows = []
    errors = []
    for state, code in RF_STATES:
        for page in [1, 2, 3]:
            suffix = "" if page == 1 else f"/page-{page}"
            url = f"https://www.redfin.com/state/{state}/filter/property-type=multifamily{suffix}"
            try:
                r = http_get(url)
                if r.status_code != 200:
                    errors.append(f"Redfin {code} page {page}: HTTP {r.status_code}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.find_all(
                    "div",
                    class_=lambda c: c and "bp-Homecard__Content" in c,
                )
                got = 0
                for card in cards:
                    rec = parse_redfin_card(card, code)
                    if rec:
                        rows.append(rec)
                        got += 1
                if got == 0:
                    break
                time.sleep(1.2)
            except Exception as ex:
                errors.append(f"Redfin {code} page {page}: {ex}")
                break
    return rows, errors


# --------- Zillow HTML ---------
def parse_zillow_listresults(html: str):
    idx = html.find('"listResults":[')
    if idx < 0:
        return []
    start = idx + len('"listResults":')
    depth = 0
    in_str = False
    esc = False
    end = start
    for i in range(start, min(len(html), start + 4_000_000)):
        c = html[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(html[start:end])
    except Exception:
        return []


def fetch_zillow():
    rows = []
    errors = []
    for url, code in Z_URLS:
        try:
            r = http_get(url)
            if r.status_code != 200:
                errors.append(f"Zillow {code}: HTTP {r.status_code}")
                continue
            results = parse_zillow_listresults(r.text)
            for p in results:
                hi = (p.get("hdpData") or {}).get("homeInfo") or {}
                home_type = hi.get("homeType", "")
                addr = clean(p.get("addressStreet") or hi.get("streetAddress") or "")
                city = clean(p.get("addressCity") or hi.get("city") or "")
                st = clean(p.get("addressState") or hi.get("state") or code)
                if st.upper() == "MA":
                    continue
                full_addr = clean(p.get("address") or "")
                blob = f"{home_type} {addr} {full_addr}"
                if home_type != "MULTI_FAMILY" and not is_multi(blob):
                    continue
                price = parse_price(p.get("price") or hi.get("price"))
                beds = p.get("beds") or hi.get("bedrooms") or 0
                baths = p.get("baths") or hi.get("bathrooms") or 0
                sqft = p.get("area") or hi.get("livingArea") or 0
                try:
                    beds_n = int(beds)
                except Exception:
                    beds_n = 0
                if beds_n >= 8:
                    units = 4
                elif beds_n >= 6:
                    units = 3
                elif beds_n >= 4:
                    units = 2
                else:
                    units = 2
                href = p.get("detailUrl") or ""
                if href.startswith("/"):
                    href = "https://www.zillow.com" + href
                rows.append({
                    "address": addr,
                    "city": city,
                    "state": st,
                    "units": units,
                    "price": price,
                    "url": href,
                    "notes": f"{home_type} {beds} bd / {baths} ba / {sqft} sqft".strip(),
                    "source": "Zillow",
                })
            time.sleep(1.5)
        except Exception as ex:
            errors.append(f"Zillow {code}: {ex}")
    return rows, errors


# --------- DB write ---------
def ensure_columns(conn) -> None:
    """Add lat/lng/dist_mi columns if missing (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(re_leads)")}
    for col, decl in (("lat", "REAL"), ("lng", "REAL"), ("dist_mi", "REAL")):
        if col not in existing:
            conn.execute(f"ALTER TABLE re_leads ADD COLUMN {col} {decl}")
    conn.commit()


def insert_leads(leads):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    cur = conn.cursor()
    cur.execute("SELECT LOWER(TRIM(address)) FROM re_leads WHERE address IS NOT NULL")
    existing = {r[0] for r in cur.fetchall() if r[0]}
    inserted = 0
    skipped = 0
    skipped_geo = 0
    skipped_radius = 0
    today = datetime.now().strftime("%Y-%m-%d")
    seen_in_batch = set()
    for ld in leads:
        addr = (ld.get("address") or "").strip().lower()
        if not addr:
            skipped += 1
            continue
        if addr in existing or addr in seen_in_batch:
            skipped += 1
            continue

        city = ld.get("city") or ""
        state = ld.get("state") or ""

        # Drive-time filter: geocode city+state, compute distance from Merrimack,
        # drop anything outside MAX_MILES (≈90 min drive). Conservative: leads
        # we cannot geocode are dropped too.
        coords = geocode(city, state)
        if coords is None:
            skipped_geo += 1
            skipped += 1
            continue
        dist = miles_from_merrimack(*coords)
        if dist > MAX_MILES:
            skipped_radius += 1
            skipped += 1
            continue

        seen_in_batch.add(addr)
        city_state = f"{city}, {state}".strip(", ")
        cur.execute(
            """INSERT INTO re_leads
            (address, city, units, price, status, gross_rent, owner_agent, phone, email, mls, notes, source, date_added, contacted, lat, lng, dist_mi)
            VALUES (?, ?, ?, ?, 'New', ?, '', '', '', ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                ld.get("address"),
                city_state,
                ld.get("units"),
                ld.get("price") or "",
                gross_rent(ld.get("units")),
                ld.get("url") or "",
                ld.get("notes") or "",
                ld.get("source"),
                today,
                coords[0],
                coords[1],
                round(dist, 2),
            ),
        )
        inserted += 1
    conn.commit()
    return inserted, skipped, skipped_geo, skipped_radius, conn


def regenerate_leads_json(conn):
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM re_leads ORDER BY date_added DESC, id DESC"
    ).fetchall()]
    with open(LEADS_JSON, "w") as f:
        json.dump(rows, f, indent=2)
    return len(rows)


def main():
    all_rows = []
    counts = {}
    errors = []
    for name, fn in [
        ("Craigslist", fetch_craigslist),
        ("Redfin", fetch_redfin),
        ("Zillow", fetch_zillow),
    ]:
        print(f"[{name}] fetching…", flush=True)
        rows, errs = fn()
        counts[name] = len(rows)
        errors.extend(errs)
        all_rows.extend(rows)
        print(f"[{name}] {len(rows)} candidate listings", flush=True)
        for e in errs:
            print(f"  ! {e}", flush=True)

    inserted, skipped, skipped_geo, skipped_radius, conn = insert_leads(all_rows)
    total = regenerate_leads_json(conn)
    conn.close()

    print()
    print("=" * 50)
    print("SCRAPE SUMMARY")
    print("=" * 50)
    for k, v in counts.items():
        print(f"  {k:14s}: {v} found")
    print(f"  Inserted             : {inserted}")
    print(f"  Skipped (dupes/empty): {skipped - skipped_geo - skipped_radius}")
    print(f"  Skipped (no geocode) : {skipped_geo}")
    print(f"  Skipped (>{MAX_MILES:.0f} mi)    : {skipped_radius}")
    print(f"  Total leads in DB    : {total}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
