"""RunScript: actions, and a status dialog."""

from __future__ import annotations

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
