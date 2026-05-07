"""Generate static/leads.json from data/dashboard.db with precomputed
house-hack metrics: monthly carry, HouseHackScore, and FHA eligibility.

Run from the repo root:
    .venv/bin/python utils/generate_leads_json.py
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "dashboard.db"
OUT_PATH = ROOT / "static" / "leads.json"
SUMMARY_PATH = ROOT / "static" / "leads_summary.json"

# ── FHA owner-occupant assumptions ────────────────────────────────────────
RATE_ANNUAL = 0.075
TERM_MONTHS = 360
DOWN_PCT = 0.035
MIP_ANNUAL = 0.0055
TAX_INS_ANNUAL = 0.015
VACANCY = 0.92

# 2024 FHA limits for NH/VT/ME (low-cost areas)
FHA_LIMITS = {
    1: 498_257,
    2: 637_950,
    3: 771_125,
    4: 958_350,
}


_MONEY_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


def parse_money(v) -> float:
    """Extract the first numeric value from a string like '$6,700/mo (...)'."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = _MONEY_RE.search(str(v))
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return 0.0


def compute_carry(price: float, gross_rent: float, units: int) -> dict:
    """Returns dict with monthly carry plus the components used to derive it."""
    if not price or not units:
        return {}

    units = max(int(units), 1)
    down = price * DOWN_PCT
    loan = price - down

    r = RATE_ANNUAL / 12.0
    n = TERM_MONTHS
    monthly_pi = loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    monthly_mip = loan * MIP_ANNUAL / 12.0
    monthly_tax_ins = price * TAX_INS_ANNUAL / 12.0
    piti = monthly_pi + monthly_mip + monthly_tax_ins

    other_units = max(units - 1, 0)
    rent_share = gross_rent * (other_units / units) if units else 0.0
    rental_income = rent_share * VACANCY

    carry = piti - rental_income
    return {
        "down_payment": round(down),
        "loan_amount": round(loan),
        "monthly_pi": round(monthly_pi),
        "monthly_mip": round(monthly_mip),
        "monthly_tax_ins": round(monthly_tax_ins),
        "monthly_piti": round(piti),
        "monthly_rental_income": round(rental_income),
        "monthly_carry": round(carry),
    }


def carry_score(carry: float) -> int:
    if carry <= 0:
        return 100
    if carry <= 400:
        return 92
    if carry <= 800:
        return 80
    if carry <= 1_200:
        return 65
    if carry <= 1_800:
        return 45
    if carry <= 2_500:
        return 25
    return 10


def fha_eligible(price: float, units: int) -> bool:
    limit = FHA_LIMITS.get(int(units) if units else 0)
    return bool(limit and price and price <= limit)


def house_hack_score(price: float, units: int, carry: float) -> int:
    score = carry_score(carry)
    if fha_eligible(price, units):
        score += 8
    if units and units >= 3:
        score += 5
    if carry <= 1_000:
        score += 5
    return min(score, 100)


def enrich(row: dict) -> dict:
    price = parse_money(row.get("price"))
    rent = parse_money(row.get("gross_rent"))
    units = int(row.get("units") or 0)

    underwriting = compute_carry(price, rent, units)
    carry = underwriting.get("monthly_carry")
    score = house_hack_score(price, units, carry) if carry is not None else None
    eligible = fha_eligible(price, units)

    return {
        **row,
        "price_num": price if price else None,
        "gross_rent_num": rent if rent else None,
        **underwriting,
        "house_hack_score": score,
        "fha_eligible": eligible,
        "fha_limit": FHA_LIMITS.get(int(units)) if units else None,
        # camelCase aliases consumed directly by static/re_leads.html
        "carry": carry,
        "houseHackScore": score,
        "fhaEligible": eligible,
        "estimatedDown": underwriting.get("down_payment"),
    }


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM re_leads ORDER BY id DESC")]
    con.close()

    enriched = [enrich(r) for r in rows]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, default=str))

    scored = [r for r in enriched if r.get("house_hack_score") is not None]
    strong = [r for r in scored if r["house_hack_score"] >= 75]
    fha = [r for r in scored if r["fha_eligible"]]
    best_carry = min((r["monthly_carry"] for r in scored), default=None)

    by_carry_tier = {
        "tenants_cover (carry<=0)": sum(1 for r in scored if r["monthly_carry"] <= 0),
        "carry_1_to_800": sum(1 for r in scored if 0 < r["monthly_carry"] <= 800),
        "carry_801_to_1500": sum(1 for r in scored if 800 < r["monthly_carry"] <= 1500),
        "carry_gt_1500": sum(1 for r in scored if r["monthly_carry"] > 1500),
    }
    by_score_tier = {
        "score_ge_75": len(strong),
        "score_45_74": sum(1 for r in scored if 45 <= r["house_hack_score"] < 75),
        "score_lt_45": sum(1 for r in scored if r["house_hack_score"] < 45),
    }

    top5 = sorted(scored, key=lambda r: (-r["house_hack_score"], r["monthly_carry"]))[:5]
    top5_brief = [
        {
            "address": ", ".join(p for p in [r.get("address"), r.get("city")] if p),
            "units": r.get("units"),
            "price": r.get("price"),
            "carry": r["monthly_carry"],
            "score": r["house_hack_score"],
            "fhaEligible": r["fha_eligible"],
        }
        for r in top5
    ]

    summary = {
        "total": len(enriched),
        "scored": len(scored),
        "skipped_no_price": len(enriched) - len(scored),
        "score_ge_75": len(strong),
        "fha_eligible": len(fha),
        "best_carry": best_carry,
        "by_carry_tier": by_carry_tier,
        "by_score_tier": by_score_tier,
        "top5": top5_brief,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))

    print(f"wrote {OUT_PATH} — {len(enriched)} leads")
    print(f"  scored: {len(scored)}")
    print(f"  score >= 75: {len(strong)}")
    print(f"  FHA eligible: {len(fha)}")
    print(f"  best carry: ${best_carry}/mo" if best_carry is not None else "  best carry: n/a")
    print(f"  carry tiers: {by_carry_tier}")
    print(f"  score tiers: {by_score_tier}")
    print(f"\nTop 5 by HouseHack Score:")
    for i, t in enumerate(top5_brief, 1):
        carry_s = f"${t['carry']}" if t["carry"] is not None else "n/a"
        fha_s = "✓ FHA" if t["fhaEligible"] else "Conv"
        print(f"  {i}. score={t['score']}  carry={carry_s}/mo  {fha_s}  {t['units']}u  {t['address']}  ({t['price']})")
    print(f"\nwrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
