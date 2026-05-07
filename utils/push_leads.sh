#!/bin/bash
set -e

ROOT="/Users/koreygendron/Documents/TradingDashboard"
GH_BIN="$HOME/.local/bin/gh"
export PATH="$HOME/.local/bin:$PATH"

cd "$ROOT"

# Regenerate leads.json from data/dashboard.db
"$ROOT/.venv/bin/python3" utils/generate_leads_json.py

# Scrub PII (phone, email) — owner names + addresses are public record and stay
"$ROOT/.venv/bin/python3" - <<'PY'
import json, pathlib
p = pathlib.Path("static/leads.json")
data = json.loads(p.read_text())
for r in data:
    r["phone"] = ""
    r["email"] = ""
p.write_text(json.dumps(data, indent=2, default=str))
print(f"Scrubbed {len(data)} leads")
PY

# Skip push if nothing changed
if git diff --quiet static/leads.json; then
  echo "No changes to leads.json — skipping push"
  exit 0
fi

LEAD_COUNT=$("$ROOT/.venv/bin/python3" -c "import json; print(len(json.load(open('static/leads.json'))))")
git add static/leads.json
git commit -m "Auto-update: $(date '+%Y-%m-%d %H:%M') — ${LEAD_COUNT} leads"
git push origin main
echo "Pushed to GitHub Pages"
