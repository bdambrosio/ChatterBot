"""Camera service — captures a JPEG still on command and publishes it.

Subscribes to ``chatter/camera/capture``, captures from the Pi camera, and
publishes ``chatter/camera/image`` tagged with the head pose at capture time
(the camera rides the head, so the desktop needs to know where it pointed).
Caches the latest pose from ``chatter/head/status``. Run on the Pi:

    python -m chatterbot.services.camera_service
"""

import base64
import time

from ..camera import CameraCapture
from ..lib import zenoh_helpers as zh
from ..lib.topics import CAMERA_CAPTURE, CAMERA_IMAGE, HEAD_STATUS


def main():
    cfg = zh.load_config()
    cc = cfg.get("camera", {})
    cam = CameraCapture(
        width=cc.get("width", 1280),
        height=cc.get("height", 720),
        quality=cc.get("quality", 85),
        hflip=cc.get("hflip", False),
        vflip=cc.get("vflip", False),
    )
    session = zh.open_session(cfg)
    pose = {"pan": None, "tilt": None}

    def on_status(_key, msg):
        pose["pan"] = msg.get("pan")
        pose["tilt"] = msg.get("tilt")

    def on_capture(_key, msg):
        jpeg = cam.capture_jpeg()
        zh.publish_json(session, CAMERA_IMAGE, {
            "ts": zh.now(),
            "request_id": msg.get("request_id"),
            "format": "jpeg_base64",
            "data_base64": base64.b64encode(jpeg).decode("ascii"),
            "width": cam.width,
            "height": cam.height,
            "head_pose": {"pan": pose["pan"], "tilt": pose["tilt"]},
            "settled": True,
        })
        print(f"camera_service: published image ({len(jpeg)} bytes)"
              f" head_pose={pose}")

    zh.declare_subscriber_json(session, HEAD_STATUS, on_status)
    zh.declare_subscriber_json(session, CAMERA_CAPTURE, on_capture)
    print("camera_service: ready, listening on", CAMERA_CAPTURE)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()
        session.close()


if __name__ == "__main__":
    main()
