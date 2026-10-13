"""Test setup: fake Kodi modules."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "fakes"))
sys.path.insert(0, str(ROOT))

import xbmc  # noqa: E402
import xbmcaddon  # noqa: E402
import xbmcgui  # noqa: E402
import xbmcplugin  # noqa: E402
import xbmcvfs  # noqa: E402


@pytest.fixture(autouse=True)
def kodi(tmp_path, monkeypatch):
    """Reset the fake Kodi environment for each test."""
    xbmc._reset()
    xbmcgui._reset()
    xbmcplugin._reset()
    xbmcaddon._reset()
    monkeypatch.setattr(xbmcvfs, "PROFILE_ROOT", tmp_path / "profile")
    return xbmc
