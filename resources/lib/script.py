"""RunScript: actions, and a status dialog."""

from __future__ import annotations

import time

import xbmcaddon
import xbmcgui

from . import actions
from . import kodilog as log
from . import settings as settings_mod
from .avr import Avr, AvrError, display_volume, is_silent
from .lang import tr

# Maximum volume choices, dB (0 dB is reference level, 80 on the display).
MAX_VOLUME_CHOICES = (-40.0, -35.0, -30.0, -25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0)


def main(argv: list[str]) -> None:
    settings = settings_mod.load()
    log.set_debug(settings.debug)
    name, args = (argv[1] if len(argv) > 1 else "status"), argv[2:]
    if name == "find_receiver":
        find_receiver()
        return
    if name == "setting":
        change_setting(settings, args[0] if args else "")
        return
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


def find_receiver() -> None:
    """Search the network, pick a receiver, save it (the service follows)."""
    from . import discovery  # noqa: PLC0415

    dialog = xbmcgui.DialogProgress()
    dialog.create(tr(32100), tr(32130))
    try:
        found = discovery.receivers()
    finally:
        dialog.close()
    if not found:
        xbmcgui.Dialog().ok(tr(32100), tr(32131))
        return
    index = 0 if len(found) == 1 else xbmcgui.Dialog().select(tr(32132), [f.label for f in found])
    if index < 0:
        return
    xbmcaddon.Addon("service.denonavr").setSetting("host", found[index].host)
    log.info(f"receiver set: {found[index].label}")
    xbmcgui.Dialog().notification(tr(32100), found[index].label, xbmcgui.NOTIFICATION_INFO)


def change_setting(settings, key: str) -> None:
    """Skin page rows: step through or enter a setting."""
    addon = xbmcaddon.Addon("service.denonavr")
    if key == "volume_step":
        index = settings_mod.VOLUME_STEPS.index(settings.volume_step) \
            if settings.volume_step in settings_mod.VOLUME_STEPS else 1
        addon.setSetting("volume_step", str((index + 1) % len(settings_mod.VOLUME_STEPS)))
    elif key == "max_volume":
        caps = MAX_VOLUME_CHOICES
        labels = [f"{cap:g} dB ({display_volume(cap):g})" for cap in caps]
        current = caps.index(settings.max_volume) if settings.max_volume in caps else -1
        index = xbmcgui.Dialog().select(tr(32005), labels, preselect=current)
        if index >= 0:
            addon.setSetting("max_volume", f"{caps[index]:g}")
    elif key == "host":
        value = xbmcgui.Dialog().input(tr(32001), settings.host)
        if value.strip():
            addon.setSetting("host", value.strip())
