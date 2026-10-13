"""DenonService: follows the receiver and publishes it for the skin.

One asyncio loop on its own thread owns the receiver: HTTP reads (in a worker
thread, one at a time), HEOS change events, and a slow poll. Kodi's threads
(Monitor, Player) hand work to the loop; nothing blocks them on the network.

When to read the receiver:
- a HEOS event (volume, mute, play state): at once, so a volume change from
  any remote shows up;
- playback starting or stopping: a few times over the next seconds, while
  the receiver locks onto the new audio format;
- a RunScript action (it notifies us): at once;
- otherwise every POLL_PLAYING s while Kodi plays, POLL_IDLE s while not.

Shutdown makes no Kodi GUI calls: Kodi stops a service while holding its own
locks, and such a call can deadlock it (see service.webostv).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading

import xbmc
import xbmcaddon

from . import kodilog as log
from . import settings as settings_mod
from .actions import REFRESH
from .avr import PORT as AVR_PORT
from .avr import Avr, AvrError, Status
from .heos import PORT as HEOS_PORT
from .heos import HeosEvents
from .state import Publisher, properties, settings_properties

# Kodi kills a service that hasn't stopped this long after it was asked to.
SHUTDOWN_BUDGET = 3.0
POLL_PLAYING, POLL_IDLE = 10.0, 30.0
# Reads after playback starts or stops, while the receiver switches format.
BURST = (1.0, 3.0, 6.0, 10.0)
# HEOS sends a burst of events while a volume knob turns; read once after.
EVENT_SETTLE = 0.2
EVENTS = {"player_volume_changed", "player_state_changed", "sources_changed",
          "groups_changed", "players_changed"}
# The skin's receiver volume bar (Denon.VolumeShow) stays up this long after a
# volume or mute change, from anywhere.
VOLUME_SHOW = 2.5
# A volume button press within this long of the last builds on the level we
# set, not on what was last read (the receiver may not have caught up).
VOLUME_CHAIN = 1.5
# Commands sent as NotifyAll with sender service.denonavr and one of these as the
# message: service.webostv's Remote Bridge (the TV remote's volume buttons), and
# Estuary YBLOD's OSD panel (NotifyAll builtin), which stays open while they act.
COMMANDS = {"volume_up", "volume_down", "mute", "power"}


class Follower:
    """The receiver as the skin sees it (loop thread)."""

    def __init__(self, host: str, publish, http_port: int = AVR_PORT, heos_port: int = HEOS_PORT,
                 settings=lambda: settings_mod.Settings()) -> None:
        self.avr = Avr(host, http_port)
        self._settings = settings
        self._steps = 0  # volume presses not sent yet (+ up)
        self._volume_task: asyncio.Task | None = None
        self._target: tuple[float, float] | None = None  # level we set (dB), when
        self._show: asyncio.TimerHandle | None = None
        self._name = ""
        self._publish = publish
        self._lock = asyncio.Lock()
        self._model = ""
        self._heos = HeosEvents(host, self._on_heos, heos_port)
        self._poll: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._timers: list[asyncio.TimerHandle] = []
        self._settle: asyncio.TimerHandle | None = None
        self.playing = False
        self.status: Status | None = None
        self.connected = False

    def start(self) -> None:
        self._heos.start()
        self._poll = asyncio.ensure_future(self._polling())

    async def close(self) -> None:
        for handle in [*self._timers, self._settle, self._show]:
            if handle is not None:
                handle.cancel()
        if self._poll is not None:
            self._poll.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poll
        await self._heos.close()

    def refresh(self) -> None:
        self._wake.set()

    def playback(self, playing: bool) -> None:
        self.playing = playing
        loop = asyncio.get_running_loop()
        for handle in self._timers:
            handle.cancel()
        self._timers = [loop.call_later(delay, self.refresh) for delay in BURST]
        self.refresh()

    # -- volume buttons --

    def volume(self, steps: int) -> None:
        """Volume up (> 0) or down by `steps` presses; presses that come
        while one is being sent go out together."""
        self._steps += steps
        if self._volume_task is None or self._volume_task.done():
            self._volume_task = asyncio.ensure_future(self._send_volume())

    async def _send_volume(self) -> None:
        loop = asyncio.get_running_loop()
        while self._steps:
            steps, self._steps = self._steps, 0
            settings = self._settings()
            async with self._lock:
                try:
                    if self._target is not None and loop.time() - self._target[1] < VOLUME_CHAIN:
                        base = self._target[0]
                    else:
                        base = (await asyncio.to_thread(self.avr.status)).volume
                    if base is None:
                        return
                    db = min(settings.max_volume, base + steps * settings.volume_step)
                    db = await asyncio.to_thread(self.avr.set_volume, db)
                except AvrError as err:
                    log.warning(f"volume: {err}")
                    return
                self._target = (db, loop.time())
                if self.status is not None:
                    self.status.volume = db
                    self._publish(properties(True, self._model, self.status, self._name))
                self._show_volume()
        self._schedule_refresh(1.0)

    async def toggle_mute(self) -> None:
        async with self._lock:
            try:
                on = not (await asyncio.to_thread(self.avr.status)).mute
                await asyncio.to_thread(self.avr.mute, on)
            except AvrError as err:
                log.warning(f"mute: {err}")
                return
            if self.status is not None:
                self.status.mute = on
                self._publish(properties(True, self._model, self.status, self._name))
            self._show_volume()
        self._schedule_refresh(1.0)

    async def toggle_power(self) -> None:
        """On, or to standby. The receiver takes a few seconds to switch, so it's
        read again over the next seconds (as after playback starts)."""
        async with self._lock:
            try:
                on = not (await asyncio.to_thread(self.avr.status)).power
                await asyncio.to_thread(self.avr.power, on)
            except AvrError as err:
                log.warning(f"power: {err}")
                return
            log.info(f"power {'on' if on else 'standby'}")
        loop = asyncio.get_running_loop()
        self._timers += [loop.call_later(delay, self.refresh) for delay in BURST]
        self.refresh()

    def _show_volume(self) -> None:
        loop = asyncio.get_running_loop()
        if self._show is not None:
            self._show.cancel()
        self._publish({"VolumeShow": "true"})
        self._show = loop.call_later(VOLUME_SHOW, lambda: self._publish({"VolumeShow": ""}))

    def _schedule_refresh(self, delay: float) -> None:
        self._timers.append(asyncio.get_running_loop().call_later(delay, self.refresh))

    def _on_heos(self, event: str, fields: dict[str, str]) -> None:
        if event not in EVENTS:
            return
        log.debug(f"HEOS {event} {fields}")
        if self._settle is not None:
            self._settle.cancel()
        self._settle = asyncio.get_running_loop().call_later(EVENT_SETTLE, self.refresh)

    async def _polling(self) -> None:
        while True:
            self._wake.clear()
            await self.read()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), POLL_PLAYING if self.playing else POLL_IDLE)

    async def read(self) -> None:
        async with self._lock:
            try:
                if not self._model:
                    self._model = (await asyncio.to_thread(self.avr.device_info)).get("ModelName", "")
                status = await asyncio.to_thread(self.avr.status)
                name = await asyncio.to_thread(self.avr.input_name, status.input) if status.power else ""
            except AvrError as err:
                if self.connected or self.status is None:
                    log.warning(f"can't reach the receiver: {err}")
                self.connected, self.status = False, Status()
                self._publish(properties(False, self._model, None, ""))
                return
            if not self.connected:
                log.info(f"receiver {self._model or '?'} at {self.avr.base}")
            previous = self.status
            if previous is not None and previous.power and status.power and \
                    (previous.volume, previous.mute) != (status.volume, status.mute):
                self._show_volume()  # changed elsewhere: a remote, Home Assistant
            self._name = name
            changed = previous is None or (status.signal, status.sound) != (previous.signal, previous.sound)
            if changed and (status.signal or status.sound):
                log.info(f"receiver: {status.signal or '-'} as {status.sound or '-'}")
            self.connected, self.status = True, status
            self._publish(properties(True, self._model, status, name))


class _Player(xbmc.Player):
    def __init__(self, service: DenonService) -> None:
        super().__init__()
        self._service = service

    def onAVStarted(self) -> None:  # noqa: N802
        self._service.on_loop(lambda f: f.playback(True))

    def onPlayBackStopped(self) -> None:  # noqa: N802
        self._service.on_loop(lambda f: f.playback(False))

    def onPlayBackEnded(self) -> None:  # noqa: N802
        self._service.on_loop(lambda f: f.playback(False))


class _Monitor(xbmc.Monitor):
    def __init__(self, service: DenonService) -> None:
        super().__init__()
        self._service = service

    def onNotification(self, sender: str, method: str, data: str) -> None:  # noqa: N802
        if sender != "service.denonavr":
            return
        command = method.rsplit(".", 1)[-1]
        if command == REFRESH:
            self._service.on_loop(lambda f: f.refresh())
        elif command == "volume_up":
            self._service.on_loop(lambda f: f.volume(1))
        elif command == "volume_down":
            self._service.on_loop(lambda f: f.volume(-1))
        elif command == "mute":
            self._service.on_loop(lambda f: asyncio.ensure_future(f.toggle_mute()))
        elif command == "power":
            self._service.on_loop(lambda f: asyncio.ensure_future(f.toggle_power()))

    def onSettingsChanged(self) -> None:  # noqa: N802
        self._service.reload()


class DenonService:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.follower: Follower | None = None
        self.publisher = Publisher()
        self.settings = settings_mod.load()
        self.closing = False

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_main, name="denonavr-loop", daemon=True)
        self._thread.start()
        log.set_debug(self.settings.debug)
        self._publish(settings_properties(self.settings))
        self._submit(self._start())
        log.info("service started")
        monitor = _Monitor(self)
        self._player = _Player(self)
        while not monitor.waitForAbort(1.0):
            pass
        self.shutdown()

    def _loop_main(self) -> None:
        assert self.loop is not None
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coro):
        assert self.loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def on_loop(self, fn) -> None:
        """Kodi thread: run fn(follower) on the loop, if there's a receiver."""
        if self.loop is None or self.closing:
            return

        def call() -> None:
            if self.follower is not None:
                fn(self.follower)

        self.loop.call_soon_threadsafe(call)

    async def _start(self) -> None:
        if not self.settings.host:
            self._publish(properties(False, "", None, ""))
            await self._find_one()
            return
        self.follower = Follower(self.settings.host, self._publish, settings=lambda: self.settings)
        self.follower.start()

    async def _find_one(self) -> None:
        """No receiver set: if exactly one answers on the network, use it
        (saving the setting restarts us with it). Otherwise wait for Find receiver."""
        from . import discovery  # noqa: PLC0415

        found = await asyncio.to_thread(discovery.receivers)
        if len(found) == 1 and not self.closing:
            log.info(f"found {found[0].label}; using it")
            xbmcaddon.Addon("service.denonavr").setSetting("host", found[0].host)
        else:
            log.info(f"no receiver set, {len(found)} found: use Find receiver")

    def _publish(self, values: dict[str, str]) -> None:
        if not self.closing:
            self.publisher.publish(values)

    async def _stop(self) -> None:
        follower, self.follower = self.follower, None
        if follower is not None:
            await follower.close()

    def reload(self) -> None:
        new = settings_mod.load()
        log.set_debug(new.debug)
        changed = new.host != self.settings.host
        self.settings = new
        self._publish(settings_properties(new))
        if changed and self.loop is not None:
            self._submit(self._restart())

    async def _restart(self) -> None:
        await self._stop()
        await self._start()

    def shutdown(self) -> None:
        log.info("service stopping")
        self.closing = True
        if self.loop is not None:
            with contextlib.suppress(Exception):
                self._submit(self._stop()).result(SHUTDOWN_BUDGET)
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread is not None:
            self._thread.join(SHUTDOWN_BUDGET)
        if self.loop is not None and not self.loop.is_running():
            self.loop.close()
        log.info("service stopped")
