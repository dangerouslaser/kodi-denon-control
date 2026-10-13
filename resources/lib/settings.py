"""The addon's settings, read once into a frozen dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import xbmcaddon

VOLUME_STEPS = (0.5, 1.0, 2.0)  # dB per press, by the volume_step setting's index


@dataclass(frozen=True)
class Settings:
    host: str = ""
    volume_step: float = 1.0
    max_volume: float = -10.0  # dB; nothing in Kodi sets the volume above this
    debug: bool = False


def load() -> Settings:
    addon = xbmcaddon.Addon("service.denonavr")
    try:
        step = VOLUME_STEPS[int(addon.getSetting("volume_step") or 1)]
    except (ValueError, IndexError):
        step = 1.0
    try:
        cap = float(addon.getSetting("max_volume") or -10)
    except ValueError:
        cap = -10.0
    return Settings(
        host=addon.getSetting("host").strip(),
        volume_step=step,
        max_volume=cap,
        debug=addon.getSetting("debug") == "true",
    )
