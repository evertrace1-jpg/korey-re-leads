#!/usr/bin/env bash
# start_all.sh — launch Streamlit dashboard + Cloudflare tunnel in one command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
PORT=8501
LOG_DIR="$ROOT/logs"
STREAMLIT_LOG="$LOG_DIR/streamlit.log"

mkdir -p "$LOG_DIR"

if [ ! -x "$PYTHON" ]; then
    echo "✗ Missing $PYTHON — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✓ Streamlit already running on :$PORT"
else
    echo "→ Starting Streamlit (logs → $STREAMLIT_LOG)…"
    cd "$ROOT"
    nohup "$PYTHON" run.py >"$STREAMLIT_LOG" 2>&1 &
    for i in $(seq 1 20); do
        sleep 1
        if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
            echo "✓ Streamlit up on :$PORT"
            break
        fi
        if [ "$i" = "20" ]; then
            echo "✗ Streamlit failed to start. Log tail:" >&2
            tail -30 "$STREAMLIT_LOG" >&2
            exit 1
        fi
    done
fi

exec "$ROOT/start_tunnel.sh"
