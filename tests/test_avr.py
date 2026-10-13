"""The receiver over HTTP and HEOS, against a fake X2700H."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from fake_avr import FakeAvr, FakeHeos
from resources.lib import actions, heos
from resources.lib.avr import Avr
from resources.lib.settings import Settings
from resources.lib.state import properties


@pytest.fixture
def fake():
    avr = FakeAvr()
    avr.start_http()
    yield avr
    avr.stop_http()


def test_status_and_input_names(fake):
    avr = Avr("127.0.0.1", fake.http_port)
    status = avr.status()
    assert (status.power, status.input, status.volume, status.mute) == (True, "GAME", -31.0, False)
    assert (status.signal, status.sound) == ("PCM ZERO", "Stereo")  # padding stripped
    assert avr.input_name("GAME") == "Kodi - yblod"
    assert avr.input_name("BD") == "CoreELEC"       # the Lite page's code for Blu-ray
    assert avr.device_info()["ModelName"] == "AVR-X2700H"


def test_standby_still_reports_the_basics(fake):
    fake.power = False
    status = Avr("127.0.0.1", fake.http_port).status()
    assert (status.power, status.volume, status.signal) == (False, -31.0, "")


def test_commands(fake):
    avr = Avr("127.0.0.1", fake.http_port)
    assert avr.set_volume(-40.3) == -40.5            # half-dB steps
    assert avr.set_volume(30) == 18.0                # the receiver's top
    avr.mute(True)
    avr.power(False)
    assert fake.commands == ["1+-40.5", "1+18.0", "1+MuteOn", "1+PowerStandby"]


def test_volume_actions_respect_the_cap(fake):
    avr = Avr("127.0.0.1", fake.http_port)
    settings = Settings(host="127.0.0.1", volume_step=1.0, max_volume=-30.0)
    assert actions.run(settings, avr, "volume_up", []) == "volume -30.0 dB"
    assert actions.run(settings, avr, "volume_up", []) == "volume -30.0 dB"  # capped
    assert actions.run(settings, avr, "volume_down", []) == "volume -31.0 dB"
    assert actions.run(settings, avr, "volume", ["-50"]) == "volume -50.0 dB"
    assert actions.run(settings, avr, "mute", []) == "mute on"              # toggle
    assert actions.run(settings, avr, "mute", ["off"]) == "mute off"
    assert actions.run(settings, avr, "nope", []) is None


@pytest.mark.parametrize(("signal", "sound", "expect"), [
    ("PCM ZERO", "Stereo", ("", "Stereo", "")),
    ("Dolby Atmos", "Dolby Atmos", ("Dolby Atmos", "Dolby Atmos", "Dolby Atmos")),
    ("Dolby Digital", "Dolby Surround", ("Dolby Digital", "Dolby Surround",
                                         "Dolby Digital > Dolby Surround")),
])
def test_skin_properties(fake, signal, sound, expect):
    fake.signal, fake.sound = signal, sound
    status = Avr("127.0.0.1", fake.http_port).status()
    props = properties(True, "AVR-X2700H", status, "Kodi - yblod")
    assert (props["Signal"], props["SoundMode"], props["Format"]) == expect
    assert (props["Volume"], props["VolumeDisplay"], props["InputName"]) == ("-31.0", "49", "Kodi - yblod")
    off = properties(True, "AVR-X2700H", dataclasses.replace(status, power=False), "")
    assert off["Power"] == "false" and off["Volume"] == "" and off["Format"] == ""
    assert properties(False, "AVR-X2700H", None, "")["Connected"] == "false"


def test_heos_lines():
    assert heos.parse(b'{"heos": {"command": "event/player_volume_changed", '
                      b'"message": "pid=1&level=40&mute=off"}}\r\n') == (
        "event/player_volume_changed", {"pid": "1", "level": "40", "mute": "off"})
    assert heos.parse(b"garbage") is None


async def test_follower_reads_on_heos_events_and_playback(fake, kodi, monkeypatch):
    from resources.lib import service

    monkeypatch.setattr(service, "POLL_IDLE", 60.0)
    monkeypatch.setattr(service, "BURST", (0.05,))
    fake_heos = FakeHeos()
    await fake_heos.start()
    published = []
    follower = service.Follower("127.0.0.1", published.append, fake.http_port, fake_heos.port)
    follower.start()
    try:
        await asyncio.wait_for(fake_heos.registered.wait(), 2)
        await _until(lambda: published)
        assert published[-1]["Volume"] == "-31.0" and published[-1]["Connected"] == "true"
        fake.volume = -25.0                           # someone turns it up
        await fake_heos.event("player_volume_changed", "pid=1&level=55&mute=off")
        await _until(lambda: published[-1]["Volume"] == "-25.0")
        fake.signal, fake.sound = "Dolby Atmos", "Dolby Atmos"
        follower.playback(True)
        await _until(lambda: published[-1]["Format"] == "Dolby Atmos")
    finally:
        await follower.close()
        await fake_heos.close()


async def test_follower_says_when_the_receiver_is_gone(kodi):
    from resources.lib import service

    published = []
    follower = service.Follower("127.0.0.1", published.append, 9, 9)  # nothing listens
    await follower.read()
    assert published[-1]["Connected"] == "false"


async def _until(check, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not check():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.02)
