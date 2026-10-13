"""Volume, mute and power actions (RunScript, keymaps, skins).

Stateless: each action talks to the receiver over HTTP itself (the receiver
takes many HTTP clients), then tells the service to refresh what it shows.
"""

from __future__ import annotations

import json

from . import kodilog as log
from .avr import Avr, AvrError
from .settings import Settings

REFRESH = "refresh"  # NotifyAll message the service listens for


def run(settings: Settings, avr: Avr, name: str, args: list[str]) -> str | None:
    """Do one action; a short result for the log, or None if unknown."""
    arg = args[0].lower() if args else ""
    if name in ("volume_up", "volume_down"):
        current = avr.status().volume
        if current is None:
            raise AvrError("the receiver didn't report its volume")
        step = settings.volume_step if name == "volume_up" else -settings.volume_step
        return f"volume {_set_volume(settings, avr, current + step)} dB"
    if name == "volume":
        return f"volume {_set_volume(settings, avr, float(arg))} dB"
    if name == "mute":
        on = (not avr.status().mute) if arg in ("", "toggle") else arg in ("on", "true", "1")
        avr.mute(on)
        return f"mute {'on' if on else 'off'}"
    if name == "power":
        on = (not avr.status().power) if arg in ("", "toggle") else arg in ("on", "true", "1")
        avr.power(on)
        return f"power {'on' if on else 'off'}"
    return None


def _set_volume(settings: Settings, avr: Avr, db: float) -> float:
    if db > settings.max_volume:
        log.info(f"volume {db} dB capped at {settings.max_volume} dB")
        db = settings.max_volume
    return avr.set_volume(db)


def notify_service() -> None:
    import xbmc  # noqa: PLC0415

    xbmc.executeJSONRPC(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "JSONRPC.NotifyAll",
        "params": {"sender": "service.denonavr", "message": REFRESH},
    }))
