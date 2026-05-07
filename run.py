"""Single launch entry point.

Usage:
    python run.py            # launches Streamlit on http://localhost:8501
    python run.py --check    # tests Tastytrade connection only

The script auto-creates a venv on first run and re-execs inside it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY_VENV = VENV / "bin" / "python"
REQ = ROOT / "requirements.txt"


def _ensure_venv() -> None:
    if PY_VENV.exists():
        return
    print("→ Creating .venv …")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    print("→ Installing requirements (one-time, ~1–2 min)…")
    subprocess.check_call(
        [str(PY_VENV), "-m", "pip", "install", "--upgrade", "pip", "wheel"]
    )
    subprocess.check_call(
        [str(PY_VENV), "-m", "pip", "install", "-r", str(REQ)]
    )


def _reexec_in_venv() -> None:
    if Path(sys.executable).resolve() == PY_VENV.resolve():
        return
    os.execv(str(PY_VENV), [str(PY_VENV), str(Path(__file__).resolve()), *sys.argv[1:]])


def _check_connection() -> int:
    print("→ Testing Tastytrade connection…")
    from utils import tasty
    try:
        label = tasty.account_label()
        bal = tasty.fetch_balances()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return 1
    print(f"✅ Connected: {label}")
    print(f"   NLV ${bal['net_liquidating_value']:,.2f}  "
          f"Cash ${bal['cash_balance']:,.2f}")
    return 0


def _launch_streamlit() -> int:
    print("→ Launching Streamlit on http://localhost:8501")
    return subprocess.call([
        str(PY_VENV), "-m", "streamlit", "run", str(ROOT / "app.py"),
        "--server.headless=false",
    ])


def main() -> int:
    _ensure_venv()
    _reexec_in_venv()
    if "--check" in sys.argv:
        return _check_connection()
    return _launch_streamlit()


if __name__ == "__main__":
    raise SystemExit(main())
