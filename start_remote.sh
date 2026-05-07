#!/usr/bin/env bash
# start_remote.sh — start Streamlit (if needed) + Cloudflare quick tunnel.
# No Cloudflare account required: --url mode auto-creates a *.trycloudflare.com URL.
set -euo pipefail

ROOT="$HOME/Documents/TradingDashboard"
CLOUDFLARED="$ROOT/bin/cloudflared"
PYTHON="$ROOT/.venv/bin/python"
PORT=8501
LOG_DIR="$ROOT/logs"
URL_FILE="$ROOT/data/last_remote_url.txt"
STREAMLIT_LOG="$LOG_DIR/streamlit.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"

mkdir -p "$LOG_DIR" "$ROOT/data"

notify() {
    osascript -e "display notification \"$2\" with title \"$1\" sound name \"Glass\"" \
        >/dev/null 2>&1 || true
}

# 1) Streamlit — start only if not already listening on the port.
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✓ Streamlit already running on :$PORT"
else
    echo "→ Starting Streamlit…"
    cd "$ROOT"
    nohup "$PYTHON" -m streamlit run app.py >"$STREAMLIT_LOG" 2>&1 &
    for i in $(seq 1 15); do
        sleep 1
        if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
            echo "✓ Streamlit up on :$PORT"
            break
        fi
        if [ "$i" = "15" ]; then
            echo "✗ Streamlit failed to start. Tail of $STREAMLIT_LOG:"
            tail -20 "$STREAMLIT_LOG"
            exit 1
        fi
    done
fi

# 2) Cloudflare quick tunnel (foreground, but URL is parsed from log).
if [ ! -x "$CLOUDFLARED" ]; then
    echo "✗ cloudflared missing at $CLOUDFLARED"
    exit 1
fi

echo "→ Starting Cloudflare quick tunnel → http://localhost:$PORT"
: >"$TUNNEL_LOG"
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" \
    >"$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

cleanup() {
    echo
    echo "→ Stopping cloudflared (PID $TUNNEL_PID)…"
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    echo "  Streamlit kept running. Stop it with: pkill -f 'streamlit run app.py'"
    exit 0
}
trap cleanup INT TERM

# 3) Poll the log until cloudflared prints the public URL (typically <15s).
URL=""
for i in $(seq 1 40); do
    URL=$(grep -hEo 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" \
              2>/dev/null | head -n 1 || true)
    [ -n "$URL" ] && break
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "✗ cloudflared exited early. Log:"
        tail -40 "$TUNNEL_LOG"
        exit 1
    fi
    sleep 1
done

if [ -z "$URL" ]; then
    echo "✗ Tunnel didn't expose a URL within 40s. Log tail:"
    tail -40 "$TUNNEL_LOG"
    kill "$TUNNEL_PID" 2>/dev/null || true
    exit 1
fi

echo "$URL" >"$URL_FILE"

cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
  │  📱  Public URL: $URL
  │  🔐  Password:   see ~/Documents/TradingDashboard/.streamlit/secrets.toml
  │  📝  Saved to:   $URL_FILE
  └──────────────────────────────────────────────────────────────┘

  Press Ctrl+C to stop the tunnel (Streamlit stays running).

EOF

notify "Trading Dashboard online" "$URL"

# 4) Block until cloudflared exits or user Ctrl+C.
wait "$TUNNEL_PID"
