"""ChatterBot desktop control panel.

Drives the pan/tilt head and asks the Pi camera for stills, displaying them.
Talks to the Pi over zenoh.

Usage:
    python -m desktop.app --connect tcp/<pi-ip-or-host>:7447
    # or set ZENOH_CONNECT; default is tcp/127.0.0.1:7447

Controls:
    Pan / Tilt sliders   live head commands (throttled)
    Center / Nod / Shake / Scan   gestures
    Capture              request a still; it appears in the image pane
"""

import argparse
import base64
import json
import os
import sys
import threading

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from chatterbot.lib.topics import (
    CAMERA_CAPTURE, CAMERA_IMAGE, HEAD_CMD, HEAD_STATUS,
)
from desktop.transport import open_session


class Bridge(QObject):
    """Marshals zenoh-thread callbacks onto the Qt GUI thread via signals."""
    image = pyqtSignal(object)
    status = pyqtSignal(object)


class ControlPanel(QWidget):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self._req_id = 0
        self._pending = None   # (pan, tilt) waiting to be sent
        self._last_sent = None

        self.setWindowTitle("ChatterBot")
        self._build_ui()

        # Inbound messages -> Qt signals -> GUI-thread slots.
        self.bridge = Bridge()
        self.bridge.image.connect(self._on_image)
        self.bridge.status.connect(self._on_status)
        self._sub_img = session.declare_subscriber(
            CAMERA_IMAGE, lambda s: self._recv(self.bridge.image, s))
        self._sub_status = session.declare_subscriber(
            HEAD_STATUS, lambda s: self._recv(self.bridge.status, s))

        # Throttle live slider commands to ~20 Hz.
        self._tx_timer = QTimer(self)
        self._tx_timer.timeout.connect(self._flush_pending)
        self._tx_timer.start(50)

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)

        controls = QVBoxLayout()
        grid = QGridLayout()

        self.pan = QSlider(Qt.Orientation.Horizontal)
        self.pan.setRange(0, 180)
        self.pan.setValue(90)
        self.pan_lbl = QLabel("pan: 90")
        self.pan.valueChanged.connect(self._on_slider)

        self.tilt = QSlider(Qt.Orientation.Horizontal)
        self.tilt.setRange(0, 180)
        self.tilt.setValue(90)
        self.tilt_lbl = QLabel("tilt: 90")
        self.tilt.valueChanged.connect(self._on_slider)

        grid.addWidget(self.pan_lbl, 0, 0)
        grid.addWidget(self.pan, 0, 1)
        grid.addWidget(self.tilt_lbl, 1, 0)
        grid.addWidget(self.tilt, 1, 1)
        controls.addLayout(grid)

        btns = QHBoxLayout()
        for label, gesture in [("Center", "center"), ("Nod", "nod"),
                               ("Shake", "shake"), ("Scan", "scan")]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, g=gesture: self._send_gesture(g))
            btns.addWidget(b)
        controls.addLayout(btns)

        self.capture_btn = QPushButton("Capture")
        self.capture_btn.clicked.connect(self._send_capture)
        controls.addWidget(self.capture_btn)

        self.status_lbl = QLabel("head: —")
        controls.addWidget(self.status_lbl)
        controls.addStretch(1)
        root.addLayout(controls)

        self.image_lbl = QLabel("no image yet")
        self.image_lbl.setMinimumSize(640, 480)
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setStyleSheet("background:#222; color:#aaa;")
        root.addWidget(self.image_lbl, 1)

    # ---- outbound ----------------------------------------------------------
    def _put(self, key, payload):
        self.session.put(key, json.dumps(payload))

    def _on_slider(self):
        self.pan_lbl.setText(f"pan: {self.pan.value()}")
        self.tilt_lbl.setText(f"tilt: {self.tilt.value()}")
        self._pending = (self.pan.value(), self.tilt.value())

    def _flush_pending(self):
        if self._pending and self._pending != self._last_sent:
            pan, tilt = self._pending
            self._put(HEAD_CMD, {"pan": pan, "tilt": tilt, "smooth": False})
            self._last_sent = self._pending

    def _send_gesture(self, gesture):
        self._put(HEAD_CMD, {"gesture": gesture})

    def _send_capture(self):
        self._req_id += 1
        self._put(CAMERA_CAPTURE, {"request_id": self._req_id})

    # ---- inbound -----------------------------------------------------------
    def _recv(self, signal, sample):
        try:
            obj = json.loads(sample.payload.to_string())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        signal.emit(obj)

    def _on_image(self, msg):
        try:
            data = base64.b64decode(msg["data_base64"])
        except (KeyError, ValueError):
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        self.image_lbl.setPixmap(pix.scaled(
            self.image_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        hp = msg.get("head_pose", {})
        self.setWindowTitle(
            f"ChatterBot — image {msg.get('width')}x{msg.get('height')} "
            f"@ pan={hp.get('pan')} tilt={hp.get('tilt')}")

    def _on_status(self, msg):
        self.status_lbl.setText(
            f"head: pan={msg.get('pan')} tilt={msg.get('tilt')} "
            f"[{msg.get('state')}]")


def wait_for_head_heartbeat(session, timeout=3.0):
    """head_service publishes status at ~5 Hz; one message within `timeout`
    proves the Pi services (not just the router) are up."""
    seen = threading.Event()
    sub = session.declare_subscriber(HEAD_STATUS, lambda _s: seen.set())
    ok = seen.wait(timeout)
    sub.undeclare()
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--connect",
        default=os.environ.get("ZENOH_CONNECT", "tcp/127.0.0.1:7447"),
        help="zenoh router endpoint of the Pi, e.g. tcp/raspberrypi.local:7447",
    )
    args = parser.parse_args()

    try:
        session = open_session(args.connect)
    except Exception as e:
        print(f"error: cannot reach zenoh router at {args.connect}: {e}",
              file=sys.stderr)
        print("hint: is the Pi up? Its DHCP address may have changed — "
              "pass --connect tcp/<pi-ip>:7447 (see STATUS.md).",
              file=sys.stderr)
        sys.exit(1)

    heartbeat = wait_for_head_heartbeat(session)
    if heartbeat:
        print("startup check: router reachable, head status heartbeat OK")
    else:
        print("warning: router reachable but no head status heartbeat — "
              "is `python -m chatterbot.launcher` running on the Pi?",
              file=sys.stderr)

    app = QApplication(sys.argv)
    panel = ControlPanel(session)
    if not heartbeat:
        panel.status_lbl.setText(
            "head: no heartbeat — launcher running on the Pi?")
    panel.resize(1100, 560)
    panel.show()
    try:
        sys.exit(app.exec())
    finally:
        session.close()


if __name__ == "__main__":
    main()
