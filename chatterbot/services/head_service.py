"""Head service — sole owner of the pan/tilt servos.

Subscribes to ``chatter/head/cmd`` and drives the HeadController; publishes
``chatter/head/status`` with the current pose. Run on the Pi:

    python -m chatterbot.services.head_service
"""

import time

from ..head import HeadController
from ..lib import zenoh_helpers as zh
from ..lib.topics import HEAD_CMD, HEAD_MODE, HEAD_STATUS


def main():
    cfg = zh.load_config()
    hc = cfg.get("head", {})
    head = HeadController(
        pan_channel=hc.get("pan_channel", 0),
        tilt_channel=hc.get("tilt_channel", 1),
        channels=hc.get("channels", 16),
        pulse_range=(hc.get("pulse_min_us", 500), hc.get("pulse_max_us", 2500)),
    )
    session = zh.open_session(cfg)
    state = {"mode": "idle", "doa_follow": False}

    def publish_status(st):
        zh.publish_json(session, HEAD_STATUS, {
            "ts": zh.now(),
            "pan": head.pan,
            "tilt": head.tilt,
            "state": st,
            "mode": state["mode"],
        })

    def on_cmd(_key, msg):
        gesture = msg.get("gesture")
        publish_status("moving")
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

    zh.declare_subscriber_json(session, HEAD_CMD, on_cmd)
    zh.declare_subscriber_json(session, HEAD_MODE, on_mode)

    head.center(settle=0)
    publish_status("idle")
    print("head_service: ready, listening on", HEAD_CMD)

    hz = max(1, hc.get("status_hz", 5))
    try:
        while True:
            time.sleep(1.0 / hz)
            publish_status("idle")
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    main()
