"""Head service — sole owner of the pan/tilt servos.

Subscribes to ``chatter/head/cmd`` and drives the HeadController; publishes
``chatter/head/status`` with the current pose. Also runs the **local DoA reflex**
(DESIGN.md §6): when ``doa_follow`` is enabled it turns the head toward whoever
is speaking, using ``chatter/voice/event`` from ``mic_driver`` — no desktop
round-trip. Run on the Pi:

    python -m chatterbot.services.head_service
"""

import math
import threading
import time
from collections import deque

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
    # must be calibrated — see docs/xvf3800-setup.md §6. Raw DoA is noisy, so a
    # circular-mean filter over a short window with a consistency gate smooths it
    # and rejects jumpy readings. Disabled until doa_follow is set, so an
    # uncalibrated mapping never moves the head on its own.
    dc = hc.get("doa", {})
    front_deg = dc.get("front_deg", 180.0)      # DoA reading that means "dead ahead"
    sign = dc.get("sign", 1.0)                   # +1/-1: which way rising DoA turns
    gain = dc.get("gain", 1.0)                   # pan degrees per degree of bearing
    pan_min = dc.get("pan_min", 10)
    pan_max = dc.get("pan_max", 170)
    deadzone = dc.get("deadzone_deg", 8)         # don't saccade for sub-deadzone errors
    cmd_cooldown = dc.get("cmd_cooldown_s", 2.0)   # suspend reflex after an explicit cmd
    settle_s = dc.get("settle_s", 0.7)           # go deaf this long after a move (servo
    #                                              noise feeds back into DoA otherwise)
    window_s = dc.get("doa_window_s", 0.8)       # smoothing window
    min_samples = dc.get("min_samples", 3)       # need this many readings to act
    min_consistency = dc.get("min_consistency", 0.5)  # 0..1 circular agreement gate
    reflex_hz = max(1, dc.get("reflex_hz", 10))

    session = zh.open_session(cfg)
    head_lock = threading.Lock()  # serialize servo writes (cmd cb vs reflex tick)
    doa_hist = deque()            # (t, doa_deg) recent talker bearings
    # `settle_until`: ignore DoA until this time (during/after a saccade) so the
    # head's own servo noise can't feed back into the bearing estimate.
    state = {"mode": "idle", "doa_follow": False, "last_cmd_t": 0.0,
             "settle_until": 0.0}

    def doa_to_pan(doa_deg):
        bearing = _wrap180(doa_deg - front_deg)        # 0 = ahead, +/- to the sides
        pan = pan_neutral + sign * gain * bearing
        return max(pan_min, min(pan_max, pan))

    def smoothed_target(now):
        """Circular mean of recent bearings + an agreement score, or None.

        Returns ``(mean_doa, consistency)`` where consistency is the resultant
        length 0..1 (1 = all readings identical). None if too few samples.
        """
        while doa_hist and (now - doa_hist[0][0]) > window_s:
            doa_hist.popleft()
        if len(doa_hist) < min_samples:
            return None
        xs = sum(math.cos(math.radians(d)) for _, d in doa_hist)
        ys = sum(math.sin(math.radians(d)) for _, d in doa_hist)
        n = len(doa_hist)
        consistency = math.hypot(xs, ys) / n
        mean_doa = math.degrees(math.atan2(ys, xs)) % 360.0
        return mean_doa, consistency

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
        if msg.get("vad") in ("start", "active"):
            doa = msg.get("doa_deg")
            # Drop readings taken while the head is moving/settling — they are
            # dominated by servo noise, not the talker.
            if doa is not None and time.time() >= state["settle_until"]:
                doa_hist.append((time.time(), doa))

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
                    and now >= state["settle_until"]
                    and (now - state["last_cmd_t"]) >= cmd_cooldown):
                target = smoothed_target(now)
                if target is not None and target[1] >= min_consistency:
                    pan_target = doa_to_pan(target[0])
                    if abs(pan_target - head.pan) >= deadzone:
                        # Saccade: one quick move to face the talker, then go deaf
                        # while the servos settle (see settle_until / on_voice).
                        with head_lock:
                            head.look_at(pan=pan_target, smooth=True,
                                         step=5, delay=0.012)
                        doa_hist.clear()
                        state["settle_until"] = time.time() + settle_s
                        reflex_moved = True

            if reflex_moved or tick % status_every == 0:
                publish_status("tracking" if reflex_moved else "idle")
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    main()
