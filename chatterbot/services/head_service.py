"""Head service — sole owner of the pan/tilt servos.

Subscribes to ``chatter/head/cmd`` and drives the HeadController; publishes
``chatter/head/status`` with the current pose. Also runs the **local DoA reflex**
(DESIGN.md §6): when ``doa_follow`` is enabled it turns the head toward whoever
is speaking, using ``chatter/voice/event`` from ``mic_driver`` — no desktop
round-trip. Run on the Pi:

    python -m chatterbot.services.head_service
"""

import threading
import time

from ..head import HeadController
from ..lib import zenoh_helpers as zh
from ..lib.topics import HEAD_CMD, HEAD_MODE, HEAD_STATUS, VOICE_EVENT


def _wrap180(deg):
    """Wrap an angle to (-180, 180]; 0 means straight ahead."""
    return (deg + 180.0) % 360.0 - 180.0


def main():
    cfg = zh.load_config()
    hc = cfg.get("head", {})
    head = HeadController(
        pan_channel=hc.get("pan_channel", 0),
        tilt_channel=hc.get("tilt_channel", 1),
        channels=hc.get("channels", 16),
        pulse_range=(hc.get("pulse_min_us", 500), hc.get("pulse_max_us", 2500)),
        pan_neutral=hc.get("pan_neutral", 90),
        tilt_neutral=hc.get("tilt_neutral", 113),
    )
    pan_neutral = hc.get("pan_neutral", 90)

    # DoA reflex tuning (DESIGN.md §6). The DoA→pan mapping is mount-specific and
    # must be calibrated — see docs/xvf3800-setup.md §6. Disabled until the
    # desktop/Jill sets doa_follow, so an uncalibrated mapping never moves on its
    # own.
    dc = hc.get("doa", {})
    front_deg = dc.get("front_deg", 180.0)     # DoA reading that means "dead ahead"
    sign = dc.get("sign", 1.0)                  # +1/-1: which way rising DoA turns
    gain = dc.get("gain", 1.0)                  # pan degrees per degree of bearing
    pan_min = dc.get("pan_min", 10)
    pan_max = dc.get("pan_max", 170)
    deadzone = dc.get("deadzone_deg", 6)        # ignore sub-deadzone corrections
    max_step = dc.get("max_step_deg", 12)       # max pan move per reflex tick (slew)
    cmd_cooldown = dc.get("cmd_cooldown_s", 2.0)  # suspend reflex after an explicit cmd
    target_ttl = dc.get("target_ttl_s", 1.5)    # forget a talker bearing this stale
    reflex_hz = max(1, dc.get("reflex_hz", 10))

    session = zh.open_session(cfg)
    head_lock = threading.Lock()  # serialize servo writes (cmd cb vs reflex tick)
    state = {
        "mode": "idle",
        "doa_follow": False,
        "target_doa": None,
        "target_t": 0.0,
        "last_cmd_t": 0.0,
    }

    def doa_to_pan(doa_deg):
        bearing = _wrap180(doa_deg - front_deg)        # 0 = ahead, +/- to the sides
        pan = pan_neutral + sign * gain * bearing
        return max(pan_min, min(pan_max, pan))

    def publish_status(st):
        zh.publish_json(session, HEAD_STATUS, {
            "ts": zh.now(),
            "pan": head.pan,
            "tilt": head.tilt,
            "state": st,
            "mode": state["mode"],
        })

    def on_cmd(_key, msg):
        # Any explicit command suspends the reflex briefly so deliberate gaze and
        # the reflex don't fight (jill-integration.md §5).
        state["last_cmd_t"] = time.time()
        with head_lock:
            publish_status("moving")
            gesture = msg.get("gesture")
            if gesture == "nod":
                head.nod()
            elif gesture == "shake":
                head.shake()
            elif gesture == "scan":
                head.scan()
            elif gesture == "center":
                head.center(settle=0)
            else:
                head.look_at(
                    pan=msg.get("pan"),
                    tilt=msg.get("tilt"),
                    smooth=msg.get("smooth", True),
                )
            publish_status("arrived")

    def on_mode(_key, msg):
        state["doa_follow"] = bool(msg.get("doa_follow", False))

    def on_voice(_key, msg):
        # Cache the latest talker bearing; the reflex tick applies it.
        if msg.get("vad") in ("start", "active"):
            doa = msg.get("doa_deg")
            if doa is not None:
                state["target_doa"] = doa
                state["target_t"] = time.time()

    zh.declare_subscriber_json(session, HEAD_CMD, on_cmd)
    zh.declare_subscriber_json(session, HEAD_MODE, on_mode)
    zh.declare_subscriber_json(session, VOICE_EVENT, on_voice)

    head.center(settle=0)
    publish_status("idle")
    print("head_service: ready, listening on", HEAD_CMD)

    status_hz = max(1, hc.get("status_hz", 5))
    status_every = max(1, round(reflex_hz / status_hz))
    period = 1.0 / reflex_hz
    tick = 0
    try:
        while True:
            time.sleep(period)
            tick += 1
            now = time.time()

            reflex_moved = False
            if (state["doa_follow"]
                    and state["target_doa"] is not None
                    and (now - state["target_t"]) <= target_ttl
                    and (now - state["last_cmd_t"]) >= cmd_cooldown):
                pan_target = doa_to_pan(state["target_doa"])
                delta = pan_target - head.pan
                if abs(delta) >= deadzone:
                    step = max(-max_step, min(max_step, delta))
                    with head_lock:
                        head.look_at(pan=head.pan + step, smooth=True,
                                     step=5, delay=0.01)
                    reflex_moved = True

            if reflex_moved or tick % status_every == 0:
                publish_status("tracking" if reflex_moved else "idle")
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    main()
