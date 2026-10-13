"""A fake Denon receiver: the HTTP interface (8080) and HEOS (1255), as the
AVR-X2700H answers them (see spec.md "Receiver facts")."""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RENAMES = [("GAME", "Kodi - yblod    "), ("Blu-ray", "CoreELEC        "), ("CBL/SAT", "Fios            ")]


class FakeAvr:
    def __init__(self) -> None:
        self.power = True
        self.input = "GAME"
        self.volume = -31.0
        self.mute = False
        self.signal = "PCM ZERO             "
        self.sound = "Stereo                                                         "
        self.commands: list[str] = []
        self.requests: list[str] = []
        self._http: ThreadingHTTPServer | None = None
        self.http_port = 0

    # -- HTTP --

    def start_http(self) -> None:
        avr = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _reply(self, body: str, code: int = 200) -> None:
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                avr.requests.append(self.path)
                self._reply(*avr.get(self.path))

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                avr.requests.append(self.path)
                self._reply(avr.post(self.path, body, self.headers.get("Content-Type", "")))

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = self._http.server_address[1]
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def stop_http(self) -> None:
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()

    def get(self, path: str) -> tuple[str, int]:
        url = urllib.parse.urlsplit(path)
        query = urllib.parse.unquote(url.query)
        if url.path == "/goform/Deviceinfo.xml":
            return ('<?xml version="1.0" encoding="utf-8" ?><Device_Info><CommApiVers>0301</CommApiVers>'
                    "<ModelName>AVR-X2700H</ModelName></Device_Info>"), 200
        if url.path == "/goform/formMainZone_MainZoneXmlStatusLite.xml":
            return (f'<?xml version="1.0" encoding="utf-8" ?><item><Power><value>{"ON" if self.power else "OFF"}'
                    f"</value></Power><InputFuncSelect><value>{self.input}</value></InputFuncSelect>"
                    "<VolumeDisplay><value>Absolute</value></VolumeDisplay>"
                    f"<MasterVolume><value>{self.volume:.1f}</value></MasterVolume>"
                    f"<Mute><value>{'on' if self.mute else 'off'}</value></Mute></item>"), 200
        if url.path == "/goform/formMainZone_MainZoneXmlStatus.xml":
            return "Error 403: Forbidden", 403
        if url.path == "/goform/formiPhoneAppPower.xml":
            self.commands.append(query)
            self.power = query.endswith("PowerOn")
            return "", 200
        if url.path == "/goform/formiPhoneAppMute.xml":
            self.commands.append(query)
            self.mute = query.endswith("MuteOn")
            return "", 200
        if url.path == "/goform/formiPhoneAppVolume.xml":
            self.commands.append(query)
            self.volume = float(query.split("+", 1)[1])
            return "", 200
        if url.path == "/goform/formiPhoneAppDirect.xml":
            self.commands.append(query)
            return "", 200
        return "Not found", 404

    def post(self, path: str, body: str, content_type: str) -> str:
        empty = '<?xml version="1.0" encoding="utf-8" ?>\n<rx>\n</rx>'
        # The real receiver answers nothing unless the declaration ends in a
        # newline, the body is text/xml, and it's on.
        if not body.startswith('<?xml version="1.0" encoding="utf-8"?>\n<tx>') \
                or "text/xml" not in content_type or not self.power:
            return empty
        replies = []
        if "GetAudioInfo" in body:
            replies.append(f'<cmd><name>GetAudioInfo</name><list><param name="signal" control="1">{self.signal}'
                           f'</param><param name="sound" control="1">{self.sound}</param>'
                           '<param name="inputmode" control="1">HDMI</param><param name="fs" control="1">'
                           "</param></list></cmd>")
        if "GetRenameSource" in body:
            entries = "".join(f"<list><name>{n}</name><rename>{r}</rename></list>" for n, r in RENAMES)
            replies.append(f"<cmd><functionrename>{entries}</functionrename></cmd>")
        return '<?xml version="1.0" encoding="utf-8" ?><rx>' + "".join(replies) + "</rx>"


class FakeHeos:
    """HEOS CLI: accepts register_for_change_events and sends events on demand."""

    def __init__(self) -> None:
        self.port = 0
        self.registered = asyncio.Event()
        self._writers: list[asyncio.StreamWriter] = []
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        for writer in self._writers:
            writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        while line := await reader.readline():
            command = line.decode().strip().removeprefix("heos://").split("?")[0]
            writer.write(json.dumps({"heos": {"command": command, "result": "success",
                                              "message": "enable=on"}}).encode() + b"\r\n")
            await writer.drain()
            if command == "system/register_for_change_events":
                self.registered.set()

    async def event(self, name: str, message: str) -> None:
        for writer in self._writers:
            writer.write(json.dumps({"heos": {"command": f"event/{name}", "message": message}}).encode()
                         + b"\r\n")
            await writer.drain()
