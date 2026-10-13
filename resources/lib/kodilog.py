"""Logging to xbmc.log with a fixed prefix."""

from __future__ import annotations

import xbmc

ADDON_ID = "service.denonavr"
PREFIX = f"[{ADDON_ID}] "
_debug_enabled = False


def set_debug(enabled: bool) -> None:
    global _debug_enabled  # noqa: PLW0603
    _debug_enabled = enabled


def debug(msg: str) -> None:
    if _debug_enabled:
        # LOGINFO so it appears without Kodi's own debug logging enabled.
        xbmc.log(PREFIX + msg, xbmc.LOGINFO)


def info(msg: str) -> None:
    xbmc.log(PREFIX + msg, xbmc.LOGINFO)


def warning(msg: str) -> None:
    xbmc.log(PREFIX + msg, xbmc.LOGWARNING)


def error(msg: str) -> None:
    xbmc.log(PREFIX + msg, xbmc.LOGERROR)
