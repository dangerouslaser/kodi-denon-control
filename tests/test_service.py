"""The service starts its loop thread and stops cleanly when Kodi asks."""

from __future__ import annotations

import threading


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
