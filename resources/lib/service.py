"""DenonService: owns the receiver connection on its own asyncio loop thread.

Kodi's threads (Monitor, Player) hand work to the loop; nothing blocks them on
network I/O. Shutdown makes no Kodi GUI calls: Kodi stops a service while
holding its own locks, and such a call can deadlock it (see service.webostv).
"""

from __future__ import annotations

import asyncio
import threading

import xbmc

from . import kodilog as log

# Kodi kills a service that hasn't stopped this long after it was asked to.
SHUTDOWN_BUDGET = 3.0


class DenonService:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_main, name="denonavr-loop", daemon=True)
        self._thread.start()
        log.info("service started")
        monitor = xbmc.Monitor()
        while not monitor.waitForAbort(1.0):
            pass
        self.shutdown()

    def _loop_main(self) -> None:
        assert self.loop is not None
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def shutdown(self) -> None:
        log.info("service stopping")
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread is not None:
            self._thread.join(SHUTDOWN_BUDGET)
        if self.loop is not None and not self.loop.is_running():
            self.loop.close()
        log.info("service stopped")
