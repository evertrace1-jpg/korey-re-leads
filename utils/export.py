"""Export RE leads to CSV for AppSheet / external consumers."""
from __future__ import annotations

import csv
from pathlib import Path

from utils import db

CSV_COLUMNS = [
    "id",
    "address",
    "city",
    "units",
    "price",
    "status",
    "gross_rent",
    "owner_agent",
    "phone",
    "email",
    "mls",
    "notes",
    "contacted",
    "date_added",
    "source",
]


def export_leads_to_csv(path: str | Path = "data/re_leads.csv") -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    leads = db.get_re_leads()
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for lead in leads:
            writer.writerow({col: lead.get(col, "") for col in CSV_COLUMNS})
    return out
