# XVF3800 on the Pi — setup & findings

How the reSpeaker XVF3800 USB 4-Mic Array is brought up on the ChatterBot Pi,
and the non-obvious facts measured during bring-up (2026-06-16). This is the
"install drivers for voice / direction / sound" answer: **there is almost no
driver to install** — the work is a udev rule and two pip packages.

## TL;DR

| Capability | What it needs | Status |
|---|---|---|
| **Sound** (capture + playback) | Nothing — UAC2 class-compliant, ALSA binds it as card `Array` | works |
| **Direction** (DoA) | `pyusb` + `libusb_package` + udev rule (USB vendor control) | works |
| **Voice** (VAD) | Same `DOA_VALUE` read as DoA (`payload[1]` = speech flag) | works |

No `seeed-voicecard` kernel module (that was for the old I2S HAT mics). No
`cmake`/build — the vendor repo ships a prebuilt `rpi_64bit/xvf_host` and a
Python control SDK, but `xvf_audio` talks to the device directly via `pyusb`.

## 1. Verify the device enumerated

```bash
lsusb | grep -i 2886:001a          # Seeed reSpeaker XVF3800 4-Mic Array
cat /proc/asound/cards             # appears as card "Array"
```

Native stream (both directions): **S16_LE, 2 channels, 16000 Hz**.

## 2. The full-duplex capture gotcha (important)

The XVF3800 is an AEC device: **its capture stream only delivers samples while a
playback stream is also open** (capture is clocked off playback so the chip has
the loudspeaker reference). Opening capture alone returns `EIO` immediately:

```bash
arecord -D hw:Array -f S16_LE -c2 -r16000 -d3 /tmp/x.wav   # EIO, 0 frames
aplay -D hw:Array -f S16_LE -c2 -r16000 /dev/zero &        # silence keepalive
arecord -D hw:Array -f S16_LE -c2 -r16000 -d3 /tmp/x.wav   # now captures audio
```

`chatterbot.xvf3800.XVF3800Audio` handles this automatically: it holds a
persistent `aplay` stream (fed from stdin) open for the whole session. The
`xvf_audio` service writes **silence when idle and TTS when speaking** into that
one stream, so it is simultaneously the capture keepalive *and* the AEC
loudspeaker reference — see DESIGN.md §7 and `docs/audio-out-design.md`.

## 3. Install the control-channel deps (DoA / VAD)

Into the project venv (no sudo):

```bash
/home/bruce/Documents/Projects/ChatterBot/.venv/bin/pip install pyusb libusb_package
```

## 4. udev rule for non-root USB access (one-time, needs sudo)

`pyusb` opens the device through libusb, which is root-only by default. Grant
access to the project user:

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001a", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-respeaker-xvf3800.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
# then unplug + replug the XVF3800 so the new perms apply to a fresh node
```

## 5. Control protocol (what `XVF3800Control` does)

DoA and VAD come from one register, read via a USB **vendor** control transfer:

- `bmRequestType` = `CTRL_IN | CTRL_TYPE_VENDOR | CTRL_RECIPIENT_DEVICE`
- `bRequest` = `0`, `wValue` = `0x80 | cmdid`, `wIndex` = `resid`
- `wLength` = `nvalues*2 + 1` (uint16 payload + 1 leading status byte)
- response byte 0 is a status code: `0` = success, `64` = retry, else error

`DOA_VALUE` = resid **20**, cmdid **18**, two uint16:
`payload[0]` = DoA 0-359°, `payload[1]` = 1 if speech detected else 0.

Other useful registers in the vendor repo's `python_control/xvf_host.py`
command table: `AEC_AZIMUTH_VALUES` (per-beam azimuths), `AEC_SPENERGY_VALUES`
(per-beam speech energy — a finer confidence than the binary VAD flag),
`AUDIO_MGR_SELECTED_AZIMUTHS` (speech-energy-selected DoA, NaN when no speech).

## 6. Open items

- **DoA frame orientation / reflex calibration:** `doa_deg` is in the device's
  frame; the 0° heading depends on how the array is mounted. The DoA→pan reflex
  (`head_service`, DESIGN.md §6) is config-driven via `config.json` `head.doa`:
  - `front_deg` — the `doa_deg` value read when a talker is **dead ahead**.
    Calibrate: enable the reflex (`chatter/head/mode {doa_follow:true}`), speak
    from straight in front, read `doa_deg` off `chatter/voice/event`, set
    `front_deg` to it.
  - `sign` — `+1` or `-1`; flip if the head turns the **wrong way**.
  - `gain` — pan° per ° of bearing (1.0 = direct; lower to under-rotate).
  - `deadzone_deg` / `max_step_deg` / `cmd_cooldown_s` — anti-jitter, slew rate,
    and how long an explicit `head/cmd` suspends the reflex.
  The reflex stays off until `doa_follow` is set, so an uncalibrated mapping
  never moves the head on its own.
- **Confidence:** `xvf_audio` currently reports a coarse confidence from the VAD
  flag. Reading `AEC_SPENERGY_VALUES` would give a graded value.
