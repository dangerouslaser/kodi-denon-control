"""The service starts its loop thread and stops cleanly when Kodi asks."""

from __future__ import annotations

import threading
import time


def test_service_runs_until_kodi_stops_it(kodi):
    from resources.lib.service import DenonService

    service = DenonService()
    runner = threading.Thread(target=service.run)
    runner.start()
    kodi._abort.set()
    runner.join(5)
    assert not runner.is_alive()
    assert service.loop is not None and service.loop.is_closed()
    assert any("service stopped" in msg for _level, msg in kodi.logs)


def test_settings_are_published_for_the_skin(kodi):
    import xbmcaddon
    import xbmcgui

    from resources.lib.service import DenonService

    xbmcaddon.settings.update({"host": "127.0.0.2", "max_volume": "-12.5"})
    service = DenonService()
    runner = threading.Thread(target=service.run)
    runner.start()
    try:
        home = xbmcgui.Window(10000)
        for _ in range(100):  # run() publishes on its own thread
            if home.getProperty("Denon.Host"):
                break
            time.sleep(0.02)
        assert home.getProperty("Denon.Host") == "127.0.0.2"
        assert home.getProperty("Denon.MaxVolume") == "-12.5"
        xbmcaddon.settings["host"] = "127.0.0.3"
        service.reload()
        assert home.getProperty("Denon.Host") == "127.0.0.3"
    finally:
        kodi._abort.set()
        runner.join(5)
