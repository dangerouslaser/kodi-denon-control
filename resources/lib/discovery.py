"""Find Denon receivers on the network.

SSDP M-SEARCH for what Denon (and Marantz) receivers announce: HEOS-era
models answer urn:schemas-denon-com:device:ACT-Denon:1, all of them
MediaRenderer:1. Each answering host is then checked over HTTP: it counts
only if its Deviceinfo.xml names a model, so TVs and speakers that are
also media renderers drop out.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from .avr import Avr, AvrError

SSDP = ("239.255.255.250", 1900)
TARGETS = ("urn:schemas-denon-com:device:ACT-Denon:1", "urn:schemas-upnp-org:device:MediaRenderer:1")
WAIT = 3.0


@dataclass(frozen=True)
class Found:
    host: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.model} ({self.host})"


def ssdp_hosts(wait: float = WAIT, targets: tuple[str, ...] = TARGETS) -> list[str]:
    """Hosts answering an M-SEARCH for any of the targets, in answer order."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.3)
    hosts: list[str] = []
    try:
        for target in targets:
            sock.sendto((f'M-SEARCH * HTTP/1.1\r\nHOST: {SSDP[0]}:{SSDP[1]}\r\nMAN: "ssdp:discover"\r\n'
                         f"MX: 2\r\nST: {target}\r\n\r\n").encode(), SSDP)
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                data, (address, _port) = sock.recvfrom(4096)
            except (TimeoutError, socket.timeout):
                continue
            host = _location_host(data) or address
            if host not in hosts:
                hosts.append(host)
    except OSError:
        pass
    finally:
        sock.close()
    return hosts


def _location_host(reply: bytes) -> str | None:
    for line in reply.decode(errors="replace").split("\r\n"):
        name, _sep, value = line.partition(":")
        if name.strip().upper() == "LOCATION":
            return urlsplit(value.strip()).hostname
    return None


def receivers(hosts: list[str] | None = None, port: int | None = None) -> list[Found]:
    """The hosts (default: whoever answers SSDP) that are Denon receivers."""
    hosts = ssdp_hosts() if hosts is None else hosts

    def check(host: str) -> Found | None:
        try:
            model = (Avr(host, port) if port else Avr(host)).device_info().get("ModelName", "")
        except AvrError:
            return None
        return Found(host, model) if model else None

    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
        return [found for found in pool.map(check, hosts) if found is not None]
