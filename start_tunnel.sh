#!/usr/bin/env bash
# start_tunnel.sh — expose http://localhost:8501 via Cloudflare quick tunnel.
# Prints a public *.trycloudflare.com URL you can open from any device.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUDFLARED="$ROOT/bin/cloudflared"
[ -x "$CLOUDFLARED" ] || CLOUDFLARED="$(command -v cloudflared || true)"
PORT=8501
LOG="$ROOT/tunnel.log"

if [ -z "$CLOUDFLARED" ] || [ ! -x "$CLOUDFLARED" ]; then
    echo "✗ cloudflared not found. Install with: brew install cloudflared" >&2
    exit 1
fi

: >"$LOG"
echo "→ Starting Cloudflare tunnel → http://localhost:$PORT"
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" \
    >>"$LOG" 2>&1 &
TUNNEL_PID=$!

cleanup() {
    echo
    echo "→ Stopping tunnel (PID $TUNNEL_PID)…"
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

URL=""
for _ in $(seq 1 40); do
    URL=$(grep -hEo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" \
              2>/dev/null | head -n 1 || true)
    [ -n "$URL" ] && break
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "✗ cloudflared exited early. Log tail:" >&2
        tail -40 "$LOG" >&2
        exit 1
    fi
    sleep 1
done

if [ -z "$URL" ]; then
    echo "✗ No public URL after 40s. Log tail:" >&2
    tail -40 "$LOG" >&2
    kill "$TUNNEL_PID" 2>/dev/null || true
    exit 1
fi

cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
  │  📱  Public URL: $URL
  │  📄  Log file:   $LOG
  └──────────────────────────────────────────────────────────────┘

  Press Ctrl+C to stop the tunnel.

EOF

wait "$TUNNEL_PID"
