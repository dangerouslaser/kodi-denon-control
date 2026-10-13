# Denon AVR Control for Kodi (service.denonavr)

Controls a Denon AV receiver from Kodi: volume, mute, power, inputs and sound
modes, plus receiver presets chosen by what's playing (sound mode, Audyssey,
dialogue, levels, dynamic range), restored when playback stops.

It shares the receiver with Home Assistant and other controllers. Commands go
over the receiver's HTTP interface, and live updates come from HEOS. The
receiver's single control-port connection is left alone unless you turn it on.

Status: early development. The design is in [spec.md](spec.md).

Pairs with the Estuary YBLOD skin (`skin.estuary.yblod`): *Skin settings → General →
Audio receiver: Denon*.

## Development

    uv run pytest          # tests, off-Kodi with fake xbmc modules
    uv run ruff check .
    scripts/deploy.sh      # copy to the Kodi box next to the receiver (Ollie)
    uv run python scripts/build_zip.py

Command tables and receiver quirks follow
[denonavr](https://github.com/ol-iver/denonavr) (MIT), the library behind
Home Assistant's Denon integration.
