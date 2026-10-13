"""Receiver state as skin properties: Window(Home).Property(Denon.*)."""

from __future__ import annotations

import xbmcgui

from .avr import Status, display_volume, is_silent

HOME = 10000
PROPS = ("Connected", "Model", "Power", "Input", "InputName", "Volume", "VolumeDisplay", "VolumePercent", "Mute",
         "Signal", "SoundMode", "Format", "VolumeShow")


def properties(connected: bool, model: str, status: Status | None, input_name: str) -> dict[str, str]:
    """The Denon.* values for this status (empty strings clear a property)."""
    values = dict.fromkeys((p for p in PROPS if p != "VolumeShow"), "")
    values["Connected"] = "true" if connected else "false"
    values["Model"] = model
    if not connected or status is None:
        return values
    values["Power"] = "true" if status.power else "false"
    if not status.power:
        return values
    values["Input"] = status.input
    values["InputName"] = input_name
    if status.volume is not None:
        values["Volume"] = f"{status.volume:.1f}"
        values["VolumeDisplay"] = f"{display_volume(status.volume):g}"
        # 0..100 of the receiver's 0..98 scale, for the skin's volume ring.
        values["VolumePercent"] = str(max(0, min(100, round(display_volume(status.volume) / 98 * 100))))
    values["Mute"] = "true" if status.mute else "false"
    if not is_silent(status.signal):
        values["Signal"] = status.signal
        values["SoundMode"] = status.sound
        # One line for the skin: "Dolby Atmos" if it plays as it comes in,
        # else "Dolby Digital > Dolby Surround".
        values["Format"] = status.signal if status.sound.lower() == status.signal.lower() \
            else " > ".join(v for v in (status.signal, status.sound) if v)
    elif status.sound:
        values["SoundMode"] = status.sound
    return values


class Publisher:
    """Writes only what changed. Not used during shutdown.

    Create it on the service's own thread: publish() runs on the loop thread,
    and creating an xbmcgui.Window there crashes Kodi (a segfault in the
    LanguageInvoker, seen on Ollie at startup). Setting properties through a
    Window made on the service thread is fine, as service.webostv does."""

    def __init__(self) -> None:
        self._window = xbmcgui.Window(HOME)
        self._last: dict[str, str] = {}

    def publish(self, values: dict[str, str]) -> None:
        window = self._window
        for key, value in values.items():
            if self._last.get(key) == value:
                continue
            self._last[key] = value
            if value:
                window.setProperty(f"Denon.{key}", value)
            else:
                window.clearProperty(f"Denon.{key}")
