"""HEOS CLI (TCP 1255): change events, so volume and mute changes from any
remote, app or Home Assistant show up at once.

HEOS takes many connections, unlike the receiver's control port. Lines are
JSON terminated by CRLF: replies to our commands and, once registered,
events like {"heos": {"command": "event/player_volume_changed",
"message": "pid=1&level=40&mute=off"}}.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from urllib.parse import parse_qsl

from . import kodilog as log

PORT = 1255
HEARTBEAT = 60.0
CONNECT_TIMEOUT = 5.0
RETRY_MIN, RETRY_MAX = 2.0, 60.0


def parse(line: bytes) -> tuple[str, dict[str, str]] | None:
    """(command, message fields) of a HEOS line, or None."""
    try:
        heos = json.loads(line)["heos"]
        command = str(heos["command"])
    except (ValueError, KeyError, TypeError):
        return None
    message = heos.get("message") or ""
    return command, dict(parse_qsl(message, keep_blank_values=True)) if "=" in message else {}


class HeosEvents:
    """Keeps a HEOS connection open and calls on_event(name, fields) for each
    event (name without the "event/" prefix). Loop thread."""

    def __init__(self, host: str, on_event: Callable[[str, dict[str, str]], None],
                 port: int = PORT) -> None:
        self._host, self._port = host, port
        self._on_event = on_event
        self._task: asyncio.Task | None = None
        self.connected = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _run(self) -> None:
        delay = RETRY_MIN
        while True:
            try:
                await self._session()
                delay = RETRY_MIN
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
                log.debug(f"HEOS: {err!r}")
            self.connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    async def _session(self) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), CONNECT_TIMEOUT)
        try:
            writer.write(b"heos://system/register_for_change_events?enable=on\r\n")
            await writer.drain()
            self.connected = True
            log.info(f"HEOS: listening for changes on {self._host}")
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), HEARTBEAT)
                except asyncio.TimeoutError:
                    writer.write(b"heos://system/heart_beat\r\n")
                    await writer.drain()
                    continue
                if not line:
                    raise ConnectionResetError("HEOS closed the connection")
                parsed = parse(line)
                if parsed is not None and parsed[0].startswith("event/"):
                    self._on_event(parsed[0][len("event/"):], parsed[1])
        finally:
            writer.close()
