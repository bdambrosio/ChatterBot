"""Minimal pan/tilt servo test — the original bring-up snippet.

Run this first to confirm wiring and pulse ranges before using the higher-level
``chatterbot.HeadController``.
"""

import time
from adafruit_servokit import ServoKit

# 16-channel PCA9685 at default address 0x40 on I2C bus 1
kit = ServoKit(channels=16)

PAN = 0    # channel the pan servo is plugged into
TILT = 1   # channel the tilt servo is plugged into

# Optional: match your servo's real pulse range for full travel.
# Many hobby servos want ~500-2500us rather than the 1000-2000 default.
kit.servo[PAN].set_pulse_width_range(500, 2500)
kit.servo[TILT].set_pulse_width_range(500, 2500)

# Center both
kit.servo[PAN].angle = 90
kit.servo[TILT].angle = 90
time.sleep(1)

# Sweep pan
for a in range(0, 181, 5):
    kit.servo[PAN].angle = a
    time.sleep(0.02)
for a in range(180, -1, -5):
    kit.servo[PAN].angle = a
    time.sleep(0.02)

kit.servo[PAN].angle = 90
