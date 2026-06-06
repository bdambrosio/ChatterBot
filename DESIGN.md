# ChatterBot — Design Notes

Status: **design only, pre-hardware.** This captures the intended architecture
so implementation can start cleanly when hardware arrives. No code committed for
mic / camera / audio yet.

## 1. What ChatterBot is

A **stationary** Raspberry Pi "companion bot" head. It listens, looks, speaks,
and moves a pan/tilt head expressively. Heavy lifting (speech-to-text,
conversation/LLM, text-to-speech, all vision) runs on a **desktop**; the Pi is a
thin real-time I/O layer for sensors and actuators.

This mirrors the pi-side / desktop-side split of the `Body` project
(`/home/bruce/Downloads/Body/`), minus all navigation/SLAM — ChatterBot doesn't
move through the world, so there is no odometry, lidar, mapping, or drive stack.

## 2. Hardware

| Part | Role | Interface |
|------|------|-----------|
| Raspberry Pi 4 | On-bot compute (I/O only) | — |
| PCA9685 16-ch servo driver | Pan/tilt head | I2C (0x40), bus 1 |
| 2× hobby servos | Pan (ch 0) + tilt (ch 1) | PWM via PCA9685 |
| reSpeaker XVF3800 USB mic | Far-field voice: AEC, beamforming, **VAD**, **DOA** | USB (UAC2 audio + control) |
| Speaker(s) | TTS playback | **Via XVF3800 output** (see §7) |
| Pi Camera Module 3 | Still capture on command | CSI / libcamera (picamera2) |

Design principle: **no audio or image processing on the Pi 4.** The XVF3800 does
voice DSP in firmware; the desktop does STT, vision, LLM, and TTS. The Pi
captures, ships, and actuates.

## 3. Process architecture

### Pi-side (`chatterbot/` package, independent processes)
- `launcher` — spawns + supervises child processes with exponential-backoff
  restart and graceful SIGTERM shutdown. (Pattern from `Body/body/launcher.py`.)
- `head_controller` — **sole owner of the servos.** Wraps the existing
  `HeadController`. Subscribes to head commands; arbitrates between desktop
  commands and the local DOA reflex (see §6).
- `mic_driver` — bridges the XVF3800: one loop captures processed PCM audio
  (ALSA), another polls the control channel for VAD/DOA. Publishes voice events
  and (gated) audio frames.
- `camera_driver` — captures a JPEG still on command, tags it with head pose.
- `audio_out` — plays TTS PCM received from the desktop, routed through the
  XVF3800 so it serves as the AEC reference (§7).
- `status` / watchdog — process health + heartbeat enforcement (Body's safety
  triad, slimmed down).

### Desktop-side
- Speech-to-text (consumes `chatter/audio/in`).
- Conversation / LLM orchestration.
- Text-to-speech (produces `chatter/audio/out`).
- **All vision**: person/object detection, deciding where to look.
- High-level gaze control: "look around" scan cycles, "center the person."

## 4. Transport: zenoh

Single unified pub/sub bus, same as Body: `zenohd` router on the Pi
(`tcp/0.0.0.0:7447`), Pi processes connect to `tcp/127.0.0.1:7447`, desktop
connects to `tcp/<pi-ip>:7447`. Reuse `Body/body/lib/zenoh_helpers.py` and the
`schemas.py` convention.

**Why zenoh is fine for speech (the obvious worry):** audio is *lighter* than
what Body already streams.
- 16 kHz mono 16-bit PCM = ~32 KB/s; 48 kHz mono = ~96 KB/s.
- Body streams OAK-D depth at ~210 KB/s over zenoh without trouble.
- Zenoh over TCP is reliable and ordered — correct for audio frames.
- LAN transport latency is sub-millisecond; the latency budget is entirely
  STT/LLM/TTS. A second transport (RTP/WebSocket) would add config and
  discovery complexity for zero benefit.

**One deviation from Body:** Body base64-encodes binary into JSON for
uniformity. For the *continuous audio stream* that wastes +33% size and CPU per
frame — publish PCM as a **raw binary zenoh payload** with seq/timestamp,
not base64-JSON. Keep base64-JSON only for discrete / on-demand messages
(camera stills, control events) where uniformity is worth it.

Audio-specific disciplines Body didn't need:
- **Sequence number + sample timestamp** on every audio frame → desktop detects
  drops/gaps.
- **Bounded / latest-wins buffering** → a slow consumer can't build an unbounded
  queue.
- **Fix sample rate + format in `config.json`** and never negotiate.

## 5. Topic map

JSON unless marked **binary**. All carry `ts` (unix epoch float), mirroring Body.

### Pi → Desktop
| Topic | Payload | Rate |
|-------|---------|------|
| `chatter/voice/event` | `{ts, vad: start\|stop, doa_deg, confidence}` | ~10–20 Hz while active |
| `chatter/audio/in` | **binary** PCM frame + `{seq, ts}` header | streamed, VAD-gated (§6) |
| `chatter/camera/image` | `{ts, request_id, format: jpeg_base64, data_base64, width, height, head_pose:{pan,tilt}, settled}` | on demand |
| `chatter/head/status` | `{ts, pan, tilt, state: idle\|moving\|arrived, mode}` | ~10 Hz / on change |
| `chatter/status` | `{ts, processes{}, heartbeat_ok, uptime_s, host{}}` | 1 Hz |

### Desktop → Pi
| Topic | Payload | Rate |
|-------|---------|------|
| `chatter/head/cmd` | `{ts, pan?, tilt?, gesture?: nod\|shake\|scan, smooth?}` | on demand |
| `chatter/head/mode` | `{ts, doa_follow: bool}` — enable/disable local DOA reflex | on demand |
| `chatter/camera/capture` | `{ts, request_id, width?, height?}` | on demand |
| `chatter/audio/out` | **binary** PCM frame + `{seq, ts}` (TTS to play) | streamed |
| `chatter/heartbeat` | `{ts, seq}` | ≥2 Hz |

## 6. Head ownership & the DOA reflex

The `head_controller` is the **only** process that writes to the servos. Three
sources want to move the head:
1. **Local DOA reflex** (Pi): voice detected at `doa_deg` → map to pan → turn to
   face the speaker. Cheap, low-latency, runs without the desktop. Because the
   bot is stationary, DOA maps directly to a pan angle.
2. **Center detected object** (desktop): vision finds a person/object off-center
   → desktop sends a corrective `head/cmd`.
3. **Look-around** (desktop): occasional pan/capture scan cycles to survey the
   room.

**Arbitration:** the desktop can toggle the DOA reflex via `chatter/head/mode`
(`doa_follow`). When the desktop is doing deliberate gaze (centering / scanning),
it turns the reflex off so they don't fight; otherwise the reflex idles the head
toward whoever speaks. This is the companion-bot analog of Body's motor-ownership
arbitration.

## 7. Audio path & the AEC gotcha

The XVF3800 does acoustic echo cancellation, but **only if it has the playback
as its reference signal.** Therefore TTS must play **through the XVF3800's output
path** (its USB audio output), *not* the Pi's headphone jack. If playback
bypasses the XVF3800, the mic hears the bot's own voice, AEC can't cancel it, and
VAD fires on its own TTS — the bot talks over itself.

**Decision (default): VAD-gated audio upstream.** The XVF3800 gives VAD for free,
so `mic_driver` ships `chatter/audio/in` only between VAD-start and VAD-stop.
Benefits: natural utterance segmentation, lower bandwidth, less idle STT load.
Continuous streaming is simpler but wasteful — keep it as a `config.json` flag,
default gated.

## 8. Camera-on-a-moving-head

The lens rides the pan/tilt head, so framing depends on head pose. Consequences:
- **Every `camera/image` includes `head_pose` + `settled`.** The desktop needs
  to know where the camera pointed to interpret the image and compute a
  corrective pan (the analog of Body shipping camera intrinsics).
- **The perception→action loop closes on the desktop** and is slow:
  `capture → ship → detect → pan cmd → servo settle → recapture`, ≈0.5–1 s+ per
  cycle. Design gaze as **slow, deliberate** behavior (center a roughly-static
  person, survey a room) — *not* a fast visual tracking servo.
- **Avoid capturing mid-motion:** either issue a compound "pan-then-capture," or
  have the desktop sequence on `head/status: arrived` before requesting capture.

## 9. Reuse-from-Body checklist
- Keep: `launcher` + backoff supervision, `zenoh_helpers.py`, `schemas.py`
  convention, config-driven tuning, `status`/`heartbeat`/watchdog safety triad.
- Drop: odometry, lidar, IMU, OAK-D depth, local map, all drive/nav tiers.
- New for ChatterBot: binary audio payloads, AEC reference routing, head
  ownership arbitration, camera-pose tagging.

## 10. Open decisions
- Audio sample rate/format (lean 16 kHz mono 16-bit for STT).
- XVF3800 control transport on arrival (USB control endpoint via `xvf_host`
  vs. I2C) — determines how `mic_driver` reads DOA/VAD.
- DOA-degrees → pan-angle mapping + smoothing (avoid jittery reflex).
- Capture resolution / JPEG quality vs. latency.
- Whether `audio/out` is streamed continuously or per-utterance.
