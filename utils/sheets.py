"""Sync RE leads from SQLite → Google Sheets (data source for AppSheet)."""
from __future__ import annotations

import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from utils import db

SHEET_KEY = os.environ.get(
    "RE_LEADS_SHEET_KEY",
    "10g__NGVazTjNYTEUtYXuAlL2G_q7rc6dvRj3oTbV3q8",
)
WORKSHEET_NAME = "leads"
CREDENTIALS_PATH = Path(os.path.expanduser("~/.config/gspread/service_account.json"))

SHEET_HEADERS = [
    "ID", "Address", "City", "Units", "Price", "Status",
    "Gross Rent", "Owner/Agent", "Phone", "Email", "MLS",
    "Notes", "Contacted", "Date Added", "Source",
]
DB_FIELDS = [
    "id", "address", "city", "units", "price", "status",
    "gross_rent", "owner_agent", "phone", "email", "mls",
    "notes", "contacted", "date_added", "source",
]
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client() -> gspread.Client:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Service account credentials not found at {CREDENTIALS_PATH}. "
            "See README/setup notes."
        )
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=SCOPES
    )
    return gspread.authorize(creds)


def _open() -> gspread.Spreadsheet:
    return _client().open_by_key(SHEET_KEY)


def sync_leads_to_sheets() -> str:
    """Wipe and rewrite the leads worksheet from SQLite. Returns sheet URL."""
    sh = _open()
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=WORKSHEET_NAME, rows=200, cols=len(SHEET_HEADERS)
        )
        try:
            sh.del_worksheet(sh.worksheet("Sheet1"))
        except gspread.WorksheetNotFound:
            pass

    leads = db.get_re_leads()
    rows = [SHEET_HEADERS]
    for lead in leads:
        rows.append([
            "" if lead.get(f) is None else str(lead.get(f))
            for f in DB_FIELDS
        ])

    ws.clear()
    ws.update(rows, range_name="A1", value_input_option="RAW")
    return sh.url
