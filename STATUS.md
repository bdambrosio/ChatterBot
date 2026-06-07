# ChatterBot — Status

_Last updated: 2026-06-06 (evening)_

## Working end-to-end ✅

First full desktop ↔ Pi bring-up is **running on real hardware**:

- **Zenoh router** (`zenohd` v1.9.0) runs on the Pi. Installed standalone binary
  at `~/zenoh/1.9.0/zenohd` (downloaded from the eclipse-zenoh GitHub release;
  it is *not* the pip package). Bare `zenohd` defaults to router mode on
  `tcp/[::]:7447`; config also in `deploy/zenohd-router.json`.
- **Pi services** (`python -m chatterbot.launcher` → `head_service` +
  `camera_service`) connect and run.
- **Desktop app** (`python -m desktop.app --connect tcp/<pi-ip>:7447`) drives
  pan/tilt via sliders, runs gestures (center/nod/shake/scan), and pulls camera
  stills into the image pane.
- This Pi's LAN IP during testing: **192.168.68.78** (DHCP — may change).

## Environment notes (the things that bit us)

- `zenohd` is a separate binary from the `eclipse-zenoh` pip lib. Match versions
  (router 1.9.0 ↔ python lib 1.9.0). `zenoh` python module has no
  `__version__`; use `importlib.metadata.version('eclipse-zenoh')`.
- **picamera2 must come from apt**, not pip (pip build fails on libcap headers,
  and it needs libcamera bindings): `sudo apt install -y python3-picamera2`,
  then ensure the venv has `include-system-site-packages = true` (the venv is
  Python 3.13 — the apt package must match that version).
- One requirements file per machine: `requirements-pi.txt` (Pi),
  `desktop/requirements.txt` (desktop, has PyQt6). The old top-level
  `requirements.txt` was removed.

## Tuning done this session

- `HeadController.scan()` angular rate slowed ~2.5× (per-step delay 0.02 → 0.05,
  ~100 deg/s). It was visibly too fast.

## Architecture reminder

Pi = thin I/O (servos + camera) over zenoh; desktop = UI + (future) heavy
lifting. Full design in `DESIGN.md`. Topic namespace `chatter/...` in
`chatterbot/lib/topics.py`.

## Next steps / open items

- reSpeaker XVF3800 mic arriving in a few days → `mic_driver` (VAD/DOA events +
  binary audio stream); see `DESIGN.md` §6–7. Remember the AEC gotcha: route TTS
  playback **through the XVF3800** output.
- Desktop-side STT / conversation / TTS not started yet.
- Local DOA→pan reflex (turn to face the speaker) — pending the mic.
- Possible polish: gesture amplitudes/speeds, smoother `look_at`, pan/tilt
  invert flags if mount orientation needs it.
- Pi IP is DHCP; consider a static lease or mDNS (`raspberrypi.local`) so the
  desktop `--connect` is stable.
