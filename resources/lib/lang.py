"""Localized strings (strings.po ids)."""

from __future__ import annotations

import xbmcaddon


def tr(string_id: int) -> str:
    return xbmcaddon.Addon("service.denonavr").getLocalizedString(string_id) or str(string_id)
