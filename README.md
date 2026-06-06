# ChatterBot

A Raspberry Pi "companion bot" head — a Python project.

## Overview

ChatterBot is a companion robot head built on a Raspberry Pi. The head moves on
two axes (pan/tilt) driven by hobby servos through an Adafruit PCA9685 16-channel
I2C PWM board.

## Hardware

- Raspberry Pi (I2C enabled: `sudo raspi-config` → Interface Options → I2C)
- Adafruit PCA9685 16-channel servo driver (default address `0x40`, I2C bus 1)
- Two servos: pan on channel 0, tilt on channel 1

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Project layout

```
chatterbot/          Python package
  head.py            HeadController — pan/tilt control + gestures
examples/
  servo_sweep.py     Minimal bring-up test (raw servokit)
main.py              Demo entry point
```

## Quick start

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
