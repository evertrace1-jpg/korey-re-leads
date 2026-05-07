"""macOS native notification + alert state tracking."""
from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

import config

ALERT_LOG = config.DATA_DIR / "alert_state.json"
COOLDOWN_SECONDS = 60 * 30  # don't re-notify for the same symbol within 30 min


def _osascript(script: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass


def notify(title: str, message: str, sound: str = "Sosumi") -> None:
    safe_title = shlex.quote(title)[1:-1].replace('"', "'")
    safe_msg = shlex.quote(message)[1:-1].replace('"', "'")
    _osascript(
        f'display notification "{safe_msg}" with title "{safe_title}" sound name "{sound}"'
    )


def _load_state() -> dict[str, float]:
    import json
    if not ALERT_LOG.exists():
        return {}
    try:
        return json.loads(ALERT_LOG.read_text())
    except (ValueError, OSError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    import json
    ALERT_LOG.write_text(json.dumps(state))


def maybe_alert_loss(symbol: str, pl_pct: float, threshold: float = -50.0) -> bool:
    """Notify once per cooldown when a position drops past threshold."""
    if pl_pct > threshold:
        return False
    state = _load_state()
    now = time.time()
    last = state.get(symbol, 0.0)
    if now - last < COOLDOWN_SECONDS:
        return False
    notify(
        title=f"⚠️ {symbol} hit {pl_pct:.1f}%",
        message=f"Position is past {threshold:.0f}% — review.",
    )
    state[symbol] = now
    _save_state(state)
    return True
