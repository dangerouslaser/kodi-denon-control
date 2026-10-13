"""RunScript: actions, and a status dialog."""

from __future__ import annotations

import time

import xbmcgui

from . import actions
from . import kodilog as log
from . import settings as settings_mod
from .avr import Avr, AvrError, display_volume, is_silent
from .lang import tr


def main(argv: list[str]) -> None:
    settings = settings_mod.load()
    log.set_debug(settings.debug)
    name, args = (argv[1] if len(argv) > 1 else "status"), argv[2:]
    if not settings.host:
        xbmcgui.Dialog().notification(tr(32100), tr(32101), xbmcgui.NOTIFICATION_WARNING)
        return
    avr = Avr(settings.host)
    try:
        if name == "status":
            show_status(avr)
            return
        if name == "osd":
            osd_menu(settings, avr)
            return
        result = actions.run(settings, avr, name, args)
    except (AvrError, ValueError) as err:
        log.warning(f"{name} {args}: {err}")
        xbmcgui.Dialog().notification(tr(32100), tr(32102), xbmcgui.NOTIFICATION_WARNING)
        return
    if result is None:
        log.warning(f"unknown action {name}")
        return
    log.info(result)
    actions.notify_service()


def show_status(avr: Avr) -> None:
    info = avr.device_info()
    status = avr.status()
    lines = [f"{tr(32110)}: {info.get('ModelName', '?')}",
             f"{tr(32111)}: {tr(32120) if status.power else tr(32121)}"]
    if status.power:
        lines.append(f"{tr(32112)}: {avr.input_name(status.input)} ({status.input})")
        if status.volume is not None:
            volume = f"{display_volume(status.volume):g} ({status.volume:.1f} dB)"
            lines.append(f"{tr(32113)}: {volume}{' · ' + tr(32122) if status.mute else ''}")
        signal = tr(32123) if is_silent(status.signal) else status.signal
        lines.append(f"{tr(32114)}: {signal}")
        lines.append(f"{tr(32115)}: {status.sound or '-'}")
    xbmcgui.Dialog().textviewer(tr(32100), "\n".join(lines))


def osd_menu(settings, avr: Avr) -> None:
    """The OSD's receiver button: what's coming in and how it plays, volume
    and mute. Stays open, refreshed after each change, like the LG TV menu."""
    model = avr.device_info().get("ModelName", "")
    title = f"Denon {model}".strip()
    last = 0
    while True:
        status = avr.status()
        if not status.power:
            if xbmcgui.Dialog().yesno(title, tr(32124)):
                avr.power(True)
                actions.notify_service()
            return
        silent = is_silent(status.signal)
        volume = (f"{display_volume(status.volume):g} ({status.volume:.1f} dB)"
                  if status.volume is not None else "-")
        menu = [
            (f"{tr(32114)}: {tr(32123) if silent else status.signal}", None),
            (f"{tr(32115)}: {status.sound or '-'}", None),
            (f"{tr(32112)}: {avr.input_name(status.input)}", None),
            (f"{tr(32113)}: {volume}", None),
            (tr(32116), ("volume_up", [])),
            (tr(32117), ("volume_down", [])),
            (f"{tr(32118)}: {tr(32120) if status.mute else tr(32119)}", ("mute", ["toggle"])),
        ]
        index = xbmcgui.Dialog().select(title, [label for label, _ in menu], preselect=last)
        if index < 0:
            return
        last = index
        action = menu[index][1]
        if action is None:
            continue  # an info line: refresh
        log.info(actions.run(settings, avr, *action) or "")
        actions.notify_service()
        time.sleep(0.3)  # let the receiver take it before reading back
