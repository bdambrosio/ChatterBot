# ChatterBot

A Raspberry Pi "companion bot" head — a Python project.

## Overview

ChatterBot is a companion robot head built on a Raspberry Pi. The head moves on
two axes (pan/tilt) driven by hobby servos through an Adafruit PCA9685 16-channel
I2C PWM board.

See `DESIGN.md` for the full pi-side / desktop-side architecture.

## Hardware

- Raspberry Pi (I2C enabled: `sudo raspi-config` → Interface Options → I2C)
- Adafruit PCA9685 16-channel servo driver (default address `0x40`, I2C bus 1)
- Two servos: pan on channel 0, tilt on channel 1
- Pi Camera Module 3 (CSI port; libcamera / picamera2)

## Architecture

The Pi runs thin I/O services; a desktop app drives them over a **zenoh** pub/sub
bus. Communication uses the `chatter/...` topic namespace (see `DESIGN.md`).

```
desktop (off-bot)                 Pi (on-bot)
  desktop/app.py    ──cmd──▶  head_service   ──▶ servos (HeadController)
                    ◀─status──
                    ──capture─▶  camera_service ──▶ Pi Camera 3
  image pane        ◀─image───
```

## Project layout

```
config.json          Shared config (zenoh endpoints, servo + camera settings)
chatterbot/          Pi-side package
  head.py            HeadController — pan/tilt control + gestures
  camera.py          CameraCapture — Pi Camera 3 still capture (picamera2)
  lib/               zenoh_helpers.py, topics.py
  services/          head_service.py, camera_service.py (zenoh processes)
  launcher.py        Supervises the Pi services
desktop/             Desktop-side app
  app.py             PyQt6 control panel: sliders, gestures, image pane
  transport.py       zenoh session to the Pi
examples/
  servo_sweep.py     Minimal servo bring-up test (raw servokit)
cli.py               Local servo test CLI (runs on the Pi)
main.py              Local head demo (runs on the Pi)
```

## Setup

**Pi (on-bot):**
```bash
python3 -m venv .venv --system-site-packages   # so apt's picamera2 is visible
source .venv/bin/activate
pip install -r requirements-pi.txt
sudo apt install -y python3-picamera2           # camera stack (not via pip)
```

**Desktop (off-bot):**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r desktop/requirements.txt
```

## Running the desktop ↔ Pi link

1. **On the Pi**, start the zenoh router, then the services:
   ```bash
   zenohd &                          # listens on tcp/0.0.0.0:7447
   python -m chatterbot.launcher     # starts head_service + camera_service
   ```
2. **On the desktop**, launch the control panel pointed at the Pi:
   ```bash
   python -m desktop.app --connect tcp/<pi-ip-or-host>:7447
   ```
   Move the pan/tilt sliders, click gesture buttons, and **Capture** to pull a
   still from the Pi camera into the image pane.

## Local servo bring-up (on the Pi, no zenoh needed)

Bring up and verify the servos:

```bash
python examples/servo_sweep.py
```

Run the demo (center, scan, nod, shake):

```bash
python main.py
```

Use the controller in your own code:

```python
from chatterbot import HeadController

head = HeadController(pan_channel=0, tilt_channel=1)
head.center()
head.look_at(pan=120, tilt=70)   # smooth move
head.nod()                       # "yes"
head.shake()                     # "no"
head.scan()                      # look around
```
