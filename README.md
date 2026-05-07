# Trading Dashboard

A Streamlit dashboard for monitoring a Tastytrade account.

## Local use

```bash
.venv/bin/python run.py
```

Opens at <http://localhost:8501>.

## Remote access (phone, work laptop, anywhere)

Run **one** command on the Mac to launch the dashboard and expose it via a Cloudflare quick tunnel:

```bash
./start_all.sh
```

This:

1. Starts the Streamlit dashboard on `localhost:8501` (skipped if it's already running).
2. Starts `cloudflared` and prints a public `https://<random>.trycloudflare.com` URL.

**Open that URL on your phone and bookmark it** — it works from any network (cellular, work WiFi, etc.). Leave the terminal open; press `Ctrl+C` to stop the tunnel (Streamlit keeps running).

To start only the tunnel (Streamlit already running):

```bash
./start_tunnel.sh
```

The tunnel log is written to `tunnel.log`; the public URL is also printed to the terminal in a banner.

### Notes

- The `*.trycloudflare.com` URL changes every time you restart the tunnel — re-bookmark it after each launch, or set up a named Cloudflare tunnel for a stable hostname.
- `cloudflared` ships with the repo at `bin/cloudflared`. If missing, install via `brew install cloudflared`.
- Streamlit auth (password) lives in `.streamlit/secrets.toml`.
