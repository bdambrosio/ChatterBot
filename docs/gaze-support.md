# ChatterBot — Pi-side support for closed-loop gaze (Tier 2)

Status: **spec / to-build.** Captures what the Pi side (`head_service`,
`camera_service`, `config.json`) must provide so the Cognitive_workbench agent
("Jill") can run a closed-loop "look at / find a target" behavior.

Read alongside `DESIGN.md` (§6 head ownership, §8 camera-on-a-moving-head) and
the agent-side vision tiers in `jill-integration.md` (the authoritative copy
lives in the Cognitive_workbench repo and is ahead of the copy here — match by
section title, not number). The control loop —
acquire (search) then center — lives **on the agent**; this doc is only the
Pi-side primitives that loop depends on. The agent decides *where* to look; the
Pi must make each move **bounded, rate-limited, and trustworthy-when-settled**.

## 1. Authoritative head geometry & limits

This section is the **source of truth** for head angles. The agent mirrors these
constants; if the hardware changes, change them here first.

These values were **measured empirically** — the head was jogged via the
(now-being-retired) `chatterbot.app` panel and the camera view read off by eye,
so they are idiosyncrasies of *this* servo mounting, not theoretical. Re-measure
after any re-mount; `cli.py`'s REPL (`pan` / `tilt` / `look` / `pos`, runs on
the Pi) is the recalibration jig once the desktop app is gone.

| Axis | Servo range (safe) | Mapping | Forward / neutral |
|---|---|---|---|
| **pan** | **10 – 170** | 0 = camera points **right**, 170 = camera points **left** (increasing pan rotates the view **left**) | ~90 (straight ahead) |
| **tilt** | **30 – 150** | 30 = camera points **vertical up**, 115 = **horizontal**, 150 = ~**45° down** (increasing tilt lowers the view) | ~115 (horizontal) |

Notes:
- **Tilt is not symmetric about 90.** Horizontal is **115**, not 90. "Look at a
  standing/seated person" framing lives around tilt **105–120**, not 90. A
  default/idle "attentive" pose should be ≈ `pan 90, tilt 113`, not `90,90`.
- Tilt is mildly non-linear (servo 30→115 spans ~90° of view; 115→150 spans
  ~45°), ≈1° view per 1° servo. Fine for coarse proportional control.
- Camera is mounted with `hflip=false, vflip=false`, so **image-left = physically
  left of the optical axis** and **image-up = physically up**. This fixes the
  correction signs the agent uses:
  - target on image **left** → rotate camera left → **increase pan**;
    target **right** → **decrease pan**.
  - target **high** in image → raise view → **decrease tilt**;
    target **low** → **increase tilt**.

## 2. Required Pi-side changes

### 2.1 Enforce the safe envelope (not just 0–180)

Today `HeadController` clamps to 0–180 and the `scan` gesture sweeps `0..180` —
both drive past the mechanically safe range and can bind the servos/mount.

- Clamp **every** commanded pan/tilt (from `head/cmd`, gestures, and the DOA
  reflex) to **pan ∈ [10,170], tilt ∈ [30,150]**, sourced from `config.json`
  (§3), not hard-coded.
- Fix `scan` to sweep **within** the pan envelope (e.g. 20→160), never 0..180.
- Ensure `nod`/`shake` deltas clamp to the envelope around whatever the current
  pose is (a nod near tilt 150 must not try to exceed 150).

This is defense-in-depth: the agent also clamps before commanding, but the Pi is
the last line and must not rely on the agent behaving.

### 2.2 Motion rate limit (speed safety)

`look_at` currently eases in fixed `step=5°, delay=0.02s` increments regardless
of distance. Add an explicit **max angular rate** so large or repeated moves
can't slew the head dangerously fast.

- Add `head.max_deg_per_s` to `config.json` (§3); `look_at` derives its
  `step`/`delay` (or sleeps) to respect it.
- Keep motion **smooth** for gaze (the agent always sends `smooth:true`); a hard
  snap (`smooth:false`) should still be rate-limited.

### 2.3 `arrived` must mean *settled* (kills capture blur)

`head_service` publishes `head/status state:"arrived"` the instant the
interpolation loop ends — before the servos physically settle. The agent
sequences capture on `arrived`, so it captures mid-settle and gets motion blur
(observed live). Make `arrived` trustworthy:

- After a move/gesture completes, wait a configurable **`head.settle_ms`**
  (default ~250 ms) **before** publishing `arrived`.
- During that window keep state `moving`. Once `arrived` is published, a capture
  is guaranteed to see a still frame.

This is the clean home for DESIGN §8's "sequence capture on `arrived`": fix the
meaning of `arrived` once, and every consumer benefits.

### 2.4 Per-request capture resolution (gaze-loop speed)

`camera/capture` currently ignores `width`/`height` and always encodes the full
`config.camera` resolution (1280×720). The gaze loop fires many captures and
only needs a small frame for the vision model — full-res wastes encode time and
LAN bandwidth per cycle.

- Honor optional `width`/`height` in the `camera/capture` payload: capture (or
  downscale on the Pi) to that size and JPEG-encode at the smaller resolution.
- Absent width/height → current default behavior (full `config.camera` size).
- The reply still tags `width`/`height` with the **actual** delivered size and
  the `head_pose` at capture.

Downscaling on the Pi is preferred over agent-side downscale because it also cuts
the JPEG-encode and the bytes on the wire — the agent will request ≈640×360 for
loop frames and full-res only for a final "here's what I centered on" shot.

Implementation note: `CameraCapture` configures picamera2 **once** at a fixed
`main` size at startup and `capture_file()` takes no size argument — so honoring
per-request width/height means downscaling the captured frame (e.g. via PIL or
numpy, a new Pi dependency) or declaring a second `lores` stream, **not** passing
a size into the capture call.

### 2.5 Neutral / idle pose — camera boots looking up (done)

`HeadController.center()` hard-coded `(90, 90)` and `head_service` calls it at
startup, but this mount's measured horizontal is tilt **115** (§1) — so the bot
booted looking ~25° **up**. Fixed: `HeadController` now takes
`pan_neutral`/`tilt_neutral` (default `90`/`113`, the attentive pose from §1),
`center()` returns to them, and `head_service` passes them from `config.json`.
`main.py` / `cli.py` inherit the new constructor defaults.

## 3. config.json additions

```jsonc
{
  "head": {
    "pan_min": 10, "pan_max": 170,      // safe envelope (§2.1)
    "tilt_min": 30, "tilt_max": 150,
    "tilt_horizontal": 115,             // reference: horizontal aim (§1)
    "pan_neutral": 90, "tilt_neutral": 113,  // attentive idle pose (§2.5, done)
    "max_deg_per_s": 120,               // rate limit (§2.2)
    "settle_ms": 250,                   // settle before "arrived" (§2.3)
    "pan_channel": 0, "tilt_channel": 1, "channels": 16,
    "pulse_min_us": 500, "pulse_max_us": 2500, "status_hz": 5
  }
}
```
(Existing `camera` block unchanged; per-request size in §2.4 overrides it.)

## 4. Topic contract impact

No new topics. Two clarified semantics:

| Topic | Change |
|---|---|
| `chatter/head/cmd` | targets clamped to the safe envelope; motion rate-limited |
| `chatter/head/status` | `state:"arrived"` now means **physically settled** (after `settle_ms`) |
| `chatter/camera/capture` | optional `width`/`height` now **honored** (downscale on Pi) |
| `chatter/camera/image` | `width`/`height` report the **actual** delivered size |

## 5. Acceptance criteria

1. Commanding `head/cmd pan:5` or `pan:200` lands at 10 / 170; `tilt:0`/`tilt:200`
   land at 30 / 150. `scan` never leaves [10,170].
2. A full-travel move's angular speed never exceeds `max_deg_per_s`.
3. A capture issued immediately after `head/status:"arrived"` is **not** motion-
   blurred.
4. `camera/capture {width:640,height:360}` returns a ~640×360 JPEG noticeably
   faster/smaller than the full-res default; omitting them returns full-res.
5. At startup the head rests at the neutral pose (≈ pan 90, tilt 113) — looking
   straight ahead, **not** angled up as `(90, 90)` would. (done)

## 6. Open / optional

- **Camera FOV** (Pi Camera Module 3): document horizontal/vertical FOV in
  degrees here. Not needed for the agent's coarse bucket control, but enables an
  optional proportional (normalized-offset → degrees) upgrade later.
- **Envelope discoverability**: the agent currently mirrors §1 as constants.
  If preferred, expose the envelope/geometry in `chatter/status` so the agent
  reads it at connect instead of hard-coding — cleaner but not required for v1.
- **Per-axis rate**: a single `max_deg_per_s` is assumed; split into pan/tilt if
  the servos differ meaningfully.

---

Note: `docs/jill-integration.md` in this repo is a shared copy of the
Cognitive_workbench design note; the authoritative version now lives in the
Cognitive_workbench repo and is ahead of the copy here.
