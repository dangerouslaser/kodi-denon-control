"""The receiver over HTTP (port 8080): status reads and commands.

Synchronous, stdlib only, so RunScript actions can use it directly; the
service calls it from a worker thread (see receiver.py). Requests are short
and the receiver's web server (mongoose) is single-threaded, so callers keep
them one at a time.

Quirks (AVR-X2700H, see spec.md "Receiver facts"):
- AppCommand POSTs must be `<?xml ...?>`, a newline, then `<tx>...</tx>`, as
  text/xml; anything else gets an empty `<rx>`. At most 5 commands each.
- In standby AppCommand answers an empty `<rx>`; the Lite status page still
  works, so power, input, volume and mute always come from there.
- The full status page answers 403.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

PORT = 8080
TIMEOUT = 3.0
LITE_STATUS = "/goform/formMainZone_MainZoneXmlStatusLite.xml"
DEVICE_INFO = "/goform/Deviceinfo.xml"
APPCOMMAND = "/goform/AppCommand.xml"
APPCOMMAND0300 = "/goform/AppCommand0300.xml"
# Volume: the receiver's display scale is dB + 80 (0..98).
DISPLAY_OFFSET = 80.0
MIN_DB, MAX_DB = -80.0, 18.0
# Lite status input codes that differ from the names in the rename list.
INPUT_ALIASES = {"BD": "Blu-ray", "MPLAY": "Media Player", "SAT/CBL": "CBL/SAT", "SAT": "CBL/SAT",
                 "TV": "TV AUDIO", "NET": "NETWORK", "BT": "Bluetooth"}
# What the receiver reports as the signal while nothing is playing.
SILENT_SIGNALS = {"PCM ZERO", "NO SIGNAL", "UNKNOWN", ""}


class AvrError(Exception):
    """The receiver didn't answer, or answered something unreadable."""


@dataclass
class Status:
    power: bool = False
    input: str = ""          # function code, e.g. GAME
    volume: float | None = None  # dB
    mute: bool = False
    signal: str = ""         # incoming audio format, e.g. "Dolby Atmos"
    sound: str = ""          # what the receiver decodes it as, e.g. "Dolby Atmos"
    extra: dict[str, str] = field(default_factory=dict)


def display_volume(db: float) -> float:
    return db + DISPLAY_OFFSET


class Avr:
    def __init__(self, host: str, port: int = PORT, timeout: float = TIMEOUT) -> None:
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
        self._names: dict[str, str] | None = None  # function code -> your name for it

    # -- transport --

    def _request(self, path: str, body: bytes | None = None) -> bytes:
        headers = {"Content-Type": "text/xml; charset=utf-8"} if body is not None else {}
        request = urllib.request.Request(self.base + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:  # noqa: S310
                return reply.read()
        except (OSError, urllib.error.URLError) as err:
            raise AvrError(f"{path}: {err}") from err

    def _xml(self, path: str, body: bytes | None = None) -> ET.Element:
        try:
            return ET.fromstring(self._request(path, body))
        except ET.ParseError as err:
            raise AvrError(f"{path}: unreadable reply ({err})") from err

    def appcommand(self, commands: list[str], path: str = APPCOMMAND) -> list[ET.Element]:
        """Run up to 5 AppCommand <cmd> elements (as XML text); their replies, in order."""
        if not 0 < len(commands) <= 5:
            raise ValueError("AppCommand takes 1 to 5 commands")
        body = '<?xml version="1.0" encoding="utf-8"?>\n<tx>' + "".join(commands) + "</tx>"
        return list(self._xml(path, body.encode()))

    def command(self, raw: str) -> None:
        """Any control-port command, sent over HTTP (no reply)."""
        self._request("/goform/formiPhoneAppDirect.xml?" + urllib.parse.quote(raw, safe="/?"))

    # -- reads --

    def device_info(self) -> dict[str, str]:
        root = self._xml(DEVICE_INFO)
        return {tag: (root.findtext(tag) or "").strip() for tag in ("ModelName", "CommApiVers")}

    def status(self) -> Status:
        lite = self._xml(LITE_STATUS)
        status = Status(
            power=_value(lite, "Power").upper() == "ON",
            input=_value(lite, "InputFuncSelect"),
            volume=_number(_value(lite, "MasterVolume")),
            mute=_value(lite, "Mute").lower() == "on",
        )
        if status.power:
            info = self.appcommand(['<cmd id="3"><name>GetAudioInfo</name><list>'
                                    '<param name="signal"/><param name="sound"/>'
                                    '<param name="inputmode"/><param name="fs"/></list></cmd>'],
                                   APPCOMMAND0300)
            params = {p.get("name"): (p.text or "").strip() for p in info[0].iter("param")} if info else {}
            status.signal = params.get("signal", "")
            status.sound = params.get("sound", "")
            status.extra = {k: v for k, v in params.items() if k in ("inputmode", "fs")}
        return status

    def input_name(self, code: str) -> str:
        """Your name for an input (the receiver's renames), e.g. GAME -> "Kodi - yblod"."""
        if self._names is None:
            try:
                reply = self.appcommand(['<cmd id="1">GetRenameSource</cmd>'])
            except AvrError:
                return code
            names = {}
            for entry in (reply[0].iter("list") if reply else ()):
                name, rename = entry.findtext("name"), entry.findtext("rename")
                if name and rename:
                    names[name.strip().upper()] = rename.strip()
            if not names:
                return code  # standby: try again next time
            self._names = names
        key = INPUT_ALIASES.get(code.upper(), code).upper()
        return self._names.get(key, code)

    # -- commands --

    def power(self, on: bool) -> None:
        self._request("/goform/formiPhoneAppPower.xml?1+" + ("PowerOn" if on else "PowerStandby"))

    def mute(self, on: bool) -> None:
        self._request("/goform/formiPhoneAppMute.xml?1+" + ("MuteOn" if on else "MuteOff"))

    def set_volume(self, db: float) -> float:
        """Set the main zone's volume in dB (half-dB steps); the level sent."""
        db = round(max(MIN_DB, min(MAX_DB, db)) * 2) / 2
        self._request(f"/goform/formiPhoneAppVolume.xml?1+{db:.1f}")
        return db


def _value(root: ET.Element, tag: str) -> str:
    return (root.findtext(f"{tag}/value") or "").strip()


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def is_silent(signal: str) -> bool:
    return signal.strip().upper() in SILENT_SIGNALS
