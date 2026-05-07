"""Geocode US city+state via OpenStreetMap Nominatim with a JSON disk cache.

Free service, no API key. Nominatim TOS requires <=1 req/sec and a real UA string.
Cache lives at data/geocode_cache.json so repeat lookups are free and we never
hammer the service even if the script is run dozens of times.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Optional, Tuple

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "geocode_cache.json")

USER_AGENT = "korey-re-leads/1.0 (drakebosco1@gmail.com)"

# Merrimack, NH (town center)
MERRIMACK_NH: Tuple[float, float] = (42.8651, -71.4934)

# Drive-time approximation: in NH/southern ME/southern VT a 90-min drive is
# ~75 mi straight-line on I-89/I-93/I-95, less on rural backroads. 75 is a
# generous cutoff that catches every real "90 min" target while excluding
# obvious northern-VT/northern-ME/White-Mountains leads.
DEFAULT_MAX_MILES = 75.0


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_cache = _load_cache()
_last_request_ts = 0.0


def _save_cache() -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_cache, f, indent=2, sort_keys=True)
    os.replace(tmp, CACHE_PATH)


def geocode(city: str, state: str) -> Optional[Tuple[float, float]]:
    """Return (lat, lng) for a US city+state, or None if not resolvable.

    Negative results are also cached to avoid repeated lookups of junk strings.
    """
    global _last_request_ts
    city = (city or "").strip()
    state = (state or "").strip().upper()
    if not city or not state:
        return None

    key = f"{city.lower()}|{state}"
    if key in _cache:
        v = _cache[key]
        return (v[0], v[1]) if v else None

    elapsed = time.time() - _last_request_ts
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "city": city,
                "state": state,
                "country": "USA",
                "format": "json",
                "limit": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        _last_request_ts = time.time()
        resp.raise_for_status()
        results = resp.json()
        if results:
            value = [float(results[0]["lat"]), float(results[0]["lon"])]
        else:
            value = None
    except Exception:
        # transient failure: do not cache, will retry next run
        return None

    _cache[key] = value
    _save_cache()
    return (value[0], value[1]) if value else None


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles."""
    r = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def miles_from_merrimack(lat: float, lng: float) -> float:
    return haversine_miles(lat, lng, *MERRIMACK_NH)
