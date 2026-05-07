"""NH multifamily real estate leads — phone-friendly card layout."""
from __future__ import annotations

import datetime as dt
import html
import re

import streamlit as st

from utils import db, export, sheets
from utils.auth import require_password

st.set_page_config(page_title="RE Leads", page_icon="🏠", layout="wide")
require_password()
db.init_db()

st.markdown(
    """
<style>
.lead-card {
    background: #1e1e1e;
    border-radius: 12px;
    padding: 16px;
    margin: 8px 0;
    border-left: 4px solid #C4714A;
}
.lead-address { font-size: 1.1em; font-weight: bold; }
.lead-meta { color: #cfcfcf; margin: 4px 0; }
.lead-price { font-size: 1.3em; font-weight: bold; color: #C4714A; }
.lead-rent { color: #9cd9a4; margin-top: 4px; }
.lead-notes { color: #e6c98a; margin-top: 6px; }
.lead-mls { color: #888; font-size: 0.85em; margin-top: 8px; }
.lead-contacted-badge {
    display: inline-block;
    background: #2d4a2d;
    color: #9cd9a4;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.8em;
    margin-left: 8px;
}
.stButton > button, .stLinkButton > a {
    min-height: 44px;
    font-size: 1em !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🏠 NH Multifamily Leads")
st.caption(
    f"3+ unit properties — updated {dt.date.today().strftime('%b %d, %Y')}"
)

top_l, top_r = st.columns([3, 1])
with top_l:
    status_choice = st.radio(
        "Status",
        ["All", "Active", "Off-Market", "Watch"],
        horizontal=True,
        label_visibility="collapsed",
    )
with top_r:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

hide_contacted = st.toggle("Hide contacted", value=False)

status_map = {
    "All": None,
    "Active": "active",
    "Off-Market": "off-market",
    "Watch": "watch",
}
leads = db.get_re_leads(
    status_filter=status_map[status_choice],
    hide_contacted=hide_contacted,
)

if not leads:
    st.info("No leads match the current filter.")

_TEL_STRIP = re.compile(r"[^\d+]")


def _tel_href(phone: str) -> str:
    digits = _TEL_STRIP.sub("", phone or "")
    return f"tel:{digits}" if digits else ""


def _esc(value) -> str:
    return html.escape(str(value)) if value not in (None, "") else ""


for lead in leads:
    units_str = f"{lead['units']} units" if lead.get("units") else "units TBD"
    status = (lead.get("status") or "").title()
    address = _esc(lead.get("address"))
    city = _esc(lead.get("city"))
    price = _esc(lead.get("price"))
    gross_rent = _esc(lead.get("gross_rent"))
    owner_agent = _esc(lead.get("owner_agent"))
    notes = _esc(lead.get("notes"))
    mls = _esc(lead.get("mls"))
    contacted_badge = (
        '<span class="lead-contacted-badge">✓ Contacted</span>'
        if lead.get("contacted")
        else ""
    )

    parts = [
        '<div class="lead-card">',
        f'<div class="lead-address">📍 {address}'
        + (f", {city}" if city else "")
        + f'{contacted_badge}</div>',
        f'<div class="lead-meta">{units_str} · '
        f'<span class="lead-price">{price}</span> · {status}</div>',
    ]
    if gross_rent:
        parts.append(f'<div class="lead-rent">💵 {gross_rent}</div>')
    if owner_agent:
        parts.append(f'<div class="lead-meta">👤 {owner_agent}</div>')
    if notes:
        parts.append(f'<div class="lead-notes">⭐ {notes}</div>')
    if mls:
        parts.append(f'<div class="lead-mls">MLS #{mls}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    btn_cols = st.columns(2)
    tel = _tel_href(lead.get("phone") or "")
    with btn_cols[0]:
        if tel:
            st.link_button(
                f"📞 Call {lead.get('phone')}",
                tel,
                use_container_width=True,
            )
        else:
            st.button(
                "📞 No phone yet",
                key=f"no_phone_{lead['id']}",
                disabled=True,
                use_container_width=True,
            )
    with btn_cols[1]:
        if lead.get("contacted"):
            if st.button(
                "↩️ Unmark",
                key=f"uncontact_{lead['id']}",
                use_container_width=True,
            ):
                db.mark_contacted(int(lead["id"]), contacted=False)
                st.rerun()
        else:
            if st.button(
                "✅ Mark Contacted",
                key=f"contact_{lead['id']}",
                use_container_width=True,
            ):
                db.mark_contacted(int(lead["id"]), contacted=True)
                st.rerun()

st.divider()

with st.expander("☁️ Sync to Google Sheets (AppSheet source)"):
    if st.button("🔄 Sync leads → Google Sheet", use_container_width=True):
        try:
            url = sheets.sync_leads_to_sheets()
            st.success("Synced.")
            st.markdown(f"[Open Sheet]({url})")
        except Exception as e:
            st.error(f"Sync failed: {e}")

with st.expander("⬇️ Export CSV (for AppSheet / Drive)"):
    if st.button("Export re_leads → data/re_leads.csv", use_container_width=True):
        path = export.export_leads_to_csv()
        st.success(f"Wrote {path}")
    csv_path = __import__("pathlib").Path("data/re_leads.csv")
    if csv_path.exists():
        st.download_button(
            "Download re_leads.csv",
            data=csv_path.read_bytes(),
            file_name="re_leads.csv",
            mime="text/csv",
            use_container_width=True,
        )

with st.expander("➕ Add Lead"):
    with st.form("add_lead", clear_on_submit=True):
        c1, c2 = st.columns(2)
        address = c1.text_input("Address")
        city = c2.text_input("City")
        c3, c4, c5 = st.columns(3)
        units = c3.number_input("Units", min_value=0, step=1, value=3)
        price = c4.text_input("Price", placeholder="$450,000")
        status = c5.selectbox("Status", ["active", "off-market", "watch"])
        gross_rent = st.text_input("Gross rent", placeholder="$4,200/mo")
        c6, c7 = st.columns(2)
        owner_agent = c6.text_input("Owner / agent")
        phone = c7.text_input("Phone", placeholder="603-555-1234")
        c8, c9 = st.columns(2)
        email = c8.text_input("Email")
        mls = c9.text_input("MLS #")
        notes = st.text_area("Notes", height=80)
        source = st.text_input("Source", value="manual")
        submitted = st.form_submit_button("Add lead", use_container_width=True)
        if submitted:
            if not address:
                st.error("Address required.")
            else:
                lead_id = db.add_re_lead(
                    address=address,
                    city=city,
                    units=int(units) if units else None,
                    price=price,
                    status=status,
                    gross_rent=gross_rent,
                    owner_agent=owner_agent,
                    phone=phone,
                    email=email,
                    mls=mls,
                    notes=notes,
                    source=source or "manual",
                )
                st.success(f"Added lead #{lead_id}: {address}")
                st.rerun()
