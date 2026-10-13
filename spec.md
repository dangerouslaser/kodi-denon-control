# service.denonavr: Kodi addon spec

Oct 12, 2026 · @dangerouslaser · status: draft for review

## Overview and goals

`service.denonavr` is a Kodi service addon that controls a Denon AV receiver on the LAN. It sets the receiver's sound per media type, the way `service.webostv` sets the TV's picture per HDR type. Development target: the AVR-X2700H at 192.168.1.29, wired to the Ollie box (Kodi in Docker, LG CX).

Goals:

- **Presets per media type.** When playback starts, apply the listening settings that fit it: dynamic volume and range, dialogue, temporary level trims, volume. The receiver's calibrated sound modes are never changed. When it stops, put back what was there before.
- **Reliable volume, no HDMI-CEC.** Kodi, the skin and the LG Remote Bridge can drive volume and mute directly.
- **Live state for the skin.** Power, input, volume, mute and sound mode as `Window(Home).Property(Denon.*)`.
- **Plays well with others.** Home Assistant and several universal remotes already control this receiver, so the addon must never depend on holding a connection they need.

Non-goals for v1:

- Zone 2.
- Tuner.
- HEOS music browsing and queues.
- Firmware updates.
- Speaker setup and Audyssey calibration. Those belong in the receiver's own menu.
- Marantz. It uses the same protocol, so it may work, but it's untested.
- Sonos. A sibling addon later; this spec keeps the receiver-facing parts separable so it can share the rules and UI.

## Key decision: HTTP for control, HEOS for live updates, control port optional

A Denon receiver has three local interfaces. The design rests on what each allows. The facts come from Denon's protocol documents, the [denonavr](https://github.com/ol-iver/denonavr) library that Home Assistant's integration is built on, and probes of the X2700H (see *Receiver facts*).

| Interface | Gives us | Limits |
| --- | --- | --- |
| **Control port**, TCP 23 ("telnet") | Every setting, a query for every setting, instant reports of every change | **One connection at a time** (denonavr README). Home Assistant may hold it. |
| **HTTP**, TCP 8080 | Any control-port command (`/goform/formiPhoneAppDirect.xml?<command>`), status reads (`/goform/AppCommand.xml`, `AppCommand0300.xml`, `formMainZone_MainZoneXmlStatusLite.xml`) | No change reports, so state must be polled. Commands get no reply, so they must be read back. |
| **HEOS CLI**, TCP 1255 | Volume and mute events for the receiver as a HEOS player; play state | Nothing about sound modes or Audyssey. Its volume is HEOS's 0–100 scale. |

Chosen:

1. **HTTP carries all commands and reads.** Commands are sent as control-port commands over `formiPhoneAppDirect.xml`, so the full command set is available with no connection to hold. Reads come from the AppCommand pages, with no more than 5 commands per request (denonavr: more than 5 is an error), plus the Lite status page.
2. **HEOS carries live updates.** One persistent connection with `system/register_for_change_events`. Volume and mute changes made by anyone (the receiver's remote, Home Assistant, the app) arrive instantly, which is what a volume display needs.
3. **The control port is an option, off by default.** Setting: *Use the receiver's control port (instant updates for every setting; not if Home Assistant or a remote uses it)*. When it's on, the control port replaces HTTP polling and HEOS events, and commands go over it too.
4. **Polling fills the gaps.** Sound mode, Audyssey and the rest are read over HTTP:
   - when playback starts, before a preset applies, to remember what to restore;
   - after a preset applies, to confirm it;
   - every 10 s while a Kodi window shows receiver status (the skin page, the volume display);
   - never while idle with nothing showing.

| Option | Verdict |
| --- | --- |
| HTTP + HEOS, control port optional | **Chosen**: full control, live volume, no conflicts |
| Control port only | Rejected: breaks or is broken by Home Assistant and the remotes |
| Vendor denonavr | Rejected: needs httpx, attrs, ftfy, asyncstdlib, defusedxml and netifaces (a C extension), which Kodi on LibreELEC and in containers can't load. Use it as the reference for commands, values and quirks instead, with credit (MIT). |

Everything is stdlib: `asyncio` streams for HEOS and the control port, and a small `asyncio` HTTP/1.1 client for 8080, so no dependency is vendored.

## Receiver facts (AVR-X2700H, read 2026-10-12)

Read-only probes, with the receiver in standby and then on.

**Connection details:**
- **Identity:** `GET :8080/goform/Deviceinfo.xml` gives ModelName `AVR-X2700H`, CommApiVers `0301`, 2 zones. That's denonavr's "AVR-X 2016" type (HTTP on 8080).
- **Basic status:** `GET :8080/goform/formMainZone_MainZoneXmlStatusLite.xml` gives Power, InputFuncSelect, VolumeDisplay (`Absolute`), MasterVolume (`-31.0`, dB) and Mute. It works in standby too.
- **Blocked:** `formMainZone_MainZoneXmlStatus.xml` returns **403**, so it's not used.
- **Port 80:** redirects to the HTTPS web setup UI, so it's not used.

**AppCommand requests** (`POST :8080/goform/AppCommand.xml` and `AppCommand0300.xml`):
- They work only as `<?xml …?>`, **a newline**, then `<tx>…</tx>`, sent with `Content-Type: text/xml; charset=utf-8`. Other forms get an empty `<rx>` or "411 Length Required".
- At most 5 commands per request.
- In standby, they return an empty `<rx>`.

**What the reads return, with the receiver on:**

| Read | Returns |
| --- | --- |
| `GetAllZonePowerStatus` / `GetAllZoneVolume` / `GetAllZoneMuteStatus` / `GetAllZoneSource` | Per zone. Volume comes in dB and as the display value (`-31.0` = `49.0`), with limit and state. |
| `GetSurroundModeStatus` | The sound mode in use (`Stereo`) |
| `GetSourceRename` | Input names. **Kodi is the `GAME` input, renamed "Kodi - yblod"**, which is how the addon knows the receiver is on Kodi. |
| `GetToneControl`, `GetECO`, `GetDimmer`, `GetAutoStandby`, `GetDeletedSource` | Those settings |
| `GetAudyssey` (0300) | Dynamic EQ, reference level offset, Dynamic Volume and MultEQ, each with a `control` flag for whether it can be changed now |
| `GetSoundMode` (0300) | The receiver's **remembered** mode for each sound-mode category (movie, music, game, pure) |
| `GetAudioInfo` (0300) | **The incoming signal and what's being decoded** (`signal` `PCM ZERO`, `sound` `Stereo`, `inputmode` `HDMI`, `fs`). The receiver's own account of the format, Atmos included. |
| `GetInputSignal` (0300) | The channels present in the input signal |
| `GetSoundModeList`, `GetActiveSpeaker` | Empty here |

**HEOS:** `heos://player/get_players` shows one player, "Denon AVR-X2700H", pid 1474783826, firmware 3.139.173, wired.

**Power:** `GET /goform/formiPhoneAppPower.xml?1+PowerStandby` puts the main zone in standby, and it works over HTTP.

**Calibration is off limits.** The receiver is fully calibrated, and its saved sound modes must not change. Denon remembers a sound mode per input and per kind of signal, so *selecting* a sound mode overwrites that memory, even if we restore it later. See *Presets*.

**Still to verify, with your go-ahead each time:**
1. That each allowed preset command (see *Presets*) takes effect over `formiPhoneAppDirect.xml` and reads back.
2. The HEOS volume scale against dB, and whether HEOS events fire when the volume changes from the receiver's own remote.
3. That power-on works over HTTP from network standby.

## Addon structure

```
service.denonavr/
├── addon.xml
├── LICENSE.txt                 # Apache-2.0, like service.webostv
├── service.py                  # entry: starts DenonService, blocks on xbmc.Monitor
├── default.py                  # entry: RunScript actions and dialogs
├── resources/
│   ├── settings.xml
│   ├── language/resource.language.en_gb/strings.po
│   └── lib/
│       ├── service.py          # DenonService: asyncio loop thread, Monitor, Player hooks
│       ├── receiver.py         # Receiver: the only code that talks to the AVR
│       ├── http.py             # minimal asyncio HTTP client (GET, POST, keep-alive off)
│       ├── commands.py         # command and value tables (from denonavr / Denon protocol)
│       ├── heos.py             # HEOS CLI: events, volume, mute
│       ├── controlport.py      # optional control-port client (one connection)
│       ├── state.py            # ReceiverState + Window(10000) property publisher
│       ├── presets.py          # Preset model, defaults, storage
│       ├── rules.py            # playback -> preset matching, apply, restore
│       ├── discovery.py        # SSDP/HEOS discovery
│       ├── actions.py          # action registry shared by every entry point
│       ├── ipc.py              # NotifyAll request/reply, as in service.webostv
│       ├── ui.py               # dialogs: status, presets editor, sound mode picker
│       └── kodilog.py
└── tests/                      # off-Kodi, with fake xbmc modules and a fake receiver
```

Shared ideas from `service.webostv`:
- the loop-thread service;
- the NotifyAll IPC;
- the property publisher;
- the playback-rules pattern of capture, apply, restore and debounce;
- clean shutdown, with no Kodi calls in close paths.

Shared code is *copied*, not imported, so the two addons ship and update independently. If both keep growing, the common parts move into a `script.module.*` later.

## Receiver model

`Receiver` (in `receiver.py`) is the only code that talks to the AVR. Everything else calls its methods or reads `ReceiverState`.

`ReceiverState` contains:
- **The basics:** power, input, volume (dB, and the receiver's 0–98 scale), mute, sound mode and incoming signal (read only).
- **The listening fields** that presets set: Dynamic EQ, reference level offset, Dynamic Volume, dynamic range compression, dialogue enhancer, centre and subwoofer trims.
- **Stamps:** `available`, plus `updated` per field, because HTTP fields can be up to one poll old.

Commands:
- **Typed methods:** `power(on)`, `set_volume(db)`, `volume_step(±)`, `mute(on)`, `select_input(name)`, `set_sound_mode(mode)`, `apply(settings: dict)`.
- **Raw commands:** `command(raw)` sends any control-port command, the equivalent of Home Assistant's `denonavr.get_command`.

`apply()` sends the commands in the order the receiver needs:
1. the listening settings first;
2. then the level trims;
3. then volume last.

Settings the receiver flags as not changeable in its current mode are skipped.

After applying, it reads back and reports anything the receiver didn't take.

## Presets per media type

**The calibration rule:** a preset never changes anything the receiver *remembers* as part of its setup. That means:
- the sound mode;
- Audyssey MultEQ;
- speaker, distance and level calibration;
- tone.

Presets only adjust settings meant to change during listening, and every change is put back when playback stops. Sound mode is not a preset field. The receiver keeps choosing its own mode per input and signal, as calibrated.

**A preset** is a named set of these settings, each optional. A field that's left out isn't touched.
- **Dynamic Volume:** off, light, medium or heavy.
- **Dynamic EQ:** on/off, and the reference level offset.
- **Dynamic range compression:** auto, off, low, mid or high. It only applies to Dolby and DTS signals.
- **Dialogue enhancer:** off, low, medium or high.
- **Centre level offset,** a temporary trim.
- **Subwoofer level offset,** a temporary trim.
- **Volume:**
  - a fixed level, or an offset from the current level;
  - a cap ("never louder than");
  - or "leave".

Each of these is to be verified on the X2700H before it's offered (see *Receiver facts*). The receiver's `control` flag also tells us when a setting can't change in the current mode, and the editor greys those out.

**Only on Kodi's input:** presets apply only when the receiver is on Kodi's input (`GAME`, "Kodi - yblod", picked in settings from the receiver's renamed inputs). Nothing changes while another source is playing.

**Rules** pick a preset when playback starts. Each rule matches on any of:
- **content:** movie, episode, music video, live TV, music, other;
- **audio format:** what the receiver reports it's decoding (`GetAudioInfo`: Dolby Atmos, TrueHD, DTS:X, DTS-HD, Dolby Digital, PCM, …), falling back to Kodi's `VideoPlayer.AudioCodec`;
- **channels:** stereo or multichannel;
- **time of day:** a night window.

The first matching rule wins. Rules are a short ordered list edited in the UI.

**Defaults are conservative.** The addon ships with no rules on, and two suggested presets you can turn on:

| Preset | Settings |
| --- | --- |
| **Night** (time window) | Dynamic Volume medium, compression high, dialogue enhancer medium, volume cap |
| **Dialogue** (episodes, live TV) | Dialogue enhancer low |

**Restore:**
- **Before applying:** capture exactly the fields the preset will change.
- **On stop:** after a short settle, so the next playlist item doesn't thrash, put them back. The exception is anything the user changed during playback, detected by comparing with what we set, which is left as the user chose.

**One-shot overrides:** "Play with receiver preset…" in the video context menu arms one preset for the next playback.

**Debounce:** quick stop/start or seeking doesn't reapply. The same preset for the next item in a playlist is a no-op.

**What the skin shows:** the receiver's own report of the format and sound mode (`Denon.Signal`, `Denon.SoundMode`), for example *Dolby Atmos · Dolby Atmos*, so you can see what the calibrated receiver is doing.

## Volume

**Volume through the addon:** the `volume` actions (up, down, set, mute) go to the receiver. They're reachable from keymaps, `RunScript`, JSON-RPC and the LG Remote Bridge.

**Remote Bridge routing (phase 2, in `service.webostv`):** a setting, *Volume buttons control: TV / Denon receiver*. With Denon selected:
- the bridge takes the remote's volume and mute buttons while Kodi is on screen;
- `service.webostv` forwards them to `service.denonavr` over IPC.

Volume control outside Kodi, with the bridge talking to the receiver itself, is a later step and is out of scope here.

**Volume display:** the skin shows a volume bar from the `Denon.Volume*` properties when the volume changes, from any source, because the HEOS events see all of them. The TV's own volume bar never shows the receiver's level.

## Kodi integration surface

**Actions** (one registry, all entry points):

| Group | Actions |
| --- | --- |
| Power | `power`, `power_on`, `power_off` |
| Volume | `volume_up`, `volume_down`, `volume` (set dB), `mute` |
| Input | `input` |
| Sound mode | `sound_mode` (set, or `next`): only on demand, never from presets |
| Presets | `preset` (apply now), `arm_preset` (next playback), `rules_enabled` |
| Raw | `command` (raw control-port command) |
| Dialogs | `ui` (status, presets, sound mode picker) |

Entry points:
- `RunScript(service.denonavr,<action>,<args>)` from skins and keymaps.
- `JSONRPC.NotifyAll` with sender `service.denonavr`.
- A context menu entry: "Play with receiver preset…".

**Skin properties** (`Window(Home).Property(...)`):

| Property | Contents |
| --- | --- |
| `Denon.Connected`, `Denon.Model`, `Denon.Power` | Connection and receiver identity |
| `Denon.Input` | Current input |
| `Denon.Volume` (dB), `Denon.VolumePercent`, `Denon.Mute` | Volume and mute |
| `Denon.SoundMode` | Current sound mode |
| `Denon.Signal` | Incoming audio format, as the receiver reports it |
| `Denon.Preset` | The preset applied for this playback, empty when none |
| `Denon.DynamicEQ`, `Denon.DynamicVolume`, `Denon.Dialogue` | Surround settings, for the skin page |

**Skin (Estuary YBLOD):**
- When the setup's audio receiver is Denon (`$EXP[setup_denon]`, added in 4.1.0+lg.15), there's a *Denon* page like the LG TV page. It shows:
  - status: input, volume and sound mode;
  - quick controls;
  - the presets and rules;
  - a "now applied" line during playback.
- The OSD gets a receiver button, and the volume bar follows the receiver.

## Settings

Kodi settings v2, three categories:

1. **Receiver:**
   - host (discovered or typed);
   - use the control port (off; with the warning about Home Assistant and remotes);
   - debug logging.
2. **Presets:**
   - presets on/off;
   - restore on stop;
   - the rules list and presets, edited in a dialog because settings v2 can't hold an ordered list;
   - night window (start and end time).
3. **Volume:**
   - step size (0.5 / 1 / 2 dB);
   - maximum volume (a safety cap for every source of volume changes in Kodi);
   - show the volume bar.

Presets and rules live in `addon_data/service.denonavr/presets.json`, not in `settings.xml`.

## Testing

- **Fake receiver** (`tests/fake_avr.py`): an asyncio server that speaks:
  - HTTP: Deviceinfo, the Lite status page, AppCommand responses and `formiPhoneAppDirect` commands that change its state;
  - HEOS: get_players, change events;
  - optionally the control port.

  It's built from the receiver facts above and the denonavr XML dump.
- **Unit tests:** command encoding and parsing, rule matching, preset apply order, restore, debounce, IPC and the property publisher, and shutdown without Kodi calls.
- **On the real receiver,** via Ollie:
  - `scripts/deploy.sh` copies the addon into the container and restarts it;
  - a manual check list per release, covering volume, each preset field and restore.

## Phases

| Phase | Scope |
| --- | --- |
| **0.1** | Connection over HTTP and HEOS; state and skin properties; power, volume, mute, input and sound mode actions; status dialog; settings; deploy to Ollie |
| **0.2** | Presets and rules with defaults, restore, one-shot override, preset editor dialog |
| **0.3** | Skin *Denon* page and receiver volume bar (Estuary YBLOD); Remote Bridge volume routing in `service.webostv` |
| Later | Optional control port; Zone 2; HEOS now-playing for music; Sonos sibling addon |

## Open questions

1. Which listening settings do you want presets to touch at all? The list above is the maximum, and each one is restored after playback.
2. Should the manual `sound_mode` action exist, for example a "next sound mode" button? It would change the receiver's remembered mode, just as its own remote does. It could be left out entirely.
