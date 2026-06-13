"""Pan/tilt head control for the ChatterBot companion robot.

Wraps an Adafruit PCA9685 (16-channel I2C PWM driver) via ``adafruit_servokit``
and exposes a small, friendly API for moving the head: absolute positioning,
smooth motion, and a few expressive gestures (nod, shake, scan).
"""

import time
from adafruit_servokit import ServoKit


class HeadController:
    """Controls the two-axis (pan/tilt) head.

    Angles are in degrees (servo 0-180). Neutral is *not* (90, 90): this mount's
    measured horizontal is tilt ~115, so the attentive forward pose is about
    (90, 113). Neutral is configurable via ``pan_neutral``/``tilt_neutral``.
    See docs/gaze-support.md §1 for the measured geometry.

    Args:
        pan_channel: PCA9685 channel the pan servo is plugged into.
        tilt_channel: PCA9685 channel the tilt servo is plugged into.
        channels: Number of channels on the PCA9685 board (16 by default).
        pulse_range: ``(min_us, max_us)`` pulse width for full servo travel.
            Many hobby servos want ~500-2500us rather than the 1000-2000
            default. Tune this to match your servos.
        pan_neutral, tilt_neutral: the neutral/attentive pose ``center()``
            returns to (measured per-mount; see docs/gaze-support.md §1).
    """

    def __init__(
        self,
        pan_channel=0,
        tilt_channel=1,
        channels=16,
        pulse_range=(500, 2500),
        pan_neutral=90,
        tilt_neutral=113,
    ):
        self.kit = ServoKit(channels=channels)
        self.pan_channel = pan_channel
        self.tilt_channel = tilt_channel
        self._pan_neutral = pan_neutral
        self._tilt_neutral = tilt_neutral

        min_us, max_us = pulse_range
        self.kit.servo[pan_channel].set_pulse_width_range(min_us, max_us)
        self.kit.servo[tilt_channel].set_pulse_width_range(min_us, max_us)

        # Track current position so we can do smooth relative moves.
        self._pan = pan_neutral
        self._tilt = tilt_neutral

    @staticmethod
    def _clamp(angle):
        return max(0, min(180, angle))

    @property
    def pan(self):
        return self._pan

    @pan.setter
    def pan(self, angle):
        self._pan = self._clamp(angle)
        self.kit.servo[self.pan_channel].angle = self._pan

    @property
    def tilt(self):
        return self._tilt

    @tilt.setter
    def tilt(self, angle):
        self._tilt = self._clamp(angle)
        self.kit.servo[self.tilt_channel].angle = self._tilt

    def center(self, settle=1.0):
        """Move both axes to the neutral/attentive pose (``*_neutral``)."""
        self.pan = self._pan_neutral
        self.tilt = self._tilt_neutral
        if settle:
            time.sleep(settle)

    def look_at(self, pan=None, tilt=None, smooth=True, step=5, delay=0.02):
        """Move the head to an absolute (pan, tilt) target.

        Args:
            pan: Target pan angle, or None to leave unchanged.
            tilt: Target tilt angle, or None to leave unchanged.
            smooth: If True, ease toward the target in ``step``-degree
                increments; if False, snap directly.
            step: Degrees per increment when smoothing.
            delay: Seconds to sleep between increments.
        """
        target_pan = self._pan if pan is None else self._clamp(pan)
        target_tilt = self._tilt if tilt is None else self._clamp(tilt)

        if not smooth:
            self.pan = target_pan
            self.tilt = target_tilt
            return

        # Interpolate both axes together so motion looks natural.
        steps = max(
            1,
            int(max(abs(target_pan - self._pan), abs(target_tilt - self._tilt)) / step),
        )
        start_pan, start_tilt = self._pan, self._tilt
        for i in range(1, steps + 1):
            frac = i / steps
            self.pan = round(start_pan + (target_pan - start_pan) * frac)
            self.tilt = round(start_tilt + (target_tilt - start_tilt) * frac)
            time.sleep(delay)

    def nod(self, times=2, amount=20, delay=0.15):
        """Nod 'yes' by tilting down and back up."""
        base = self._tilt
        for _ in range(times):
            self.look_at(tilt=base + amount, delay=delay / 4)
            time.sleep(delay)
            self.look_at(tilt=base - amount, delay=delay / 4)
            time.sleep(delay)
        self.look_at(tilt=base)

    def shake(self, times=2, amount=25, delay=0.15):
        """Shake 'no' by panning side to side."""
        base = self._pan
        for _ in range(times):
            self.look_at(pan=base + amount, delay=delay / 4)
            time.sleep(delay)
            self.look_at(pan=base - amount, delay=delay / 4)
            time.sleep(delay)
        self.look_at(pan=base)

    def scan(self, low=0, high=180, step=5, delay=0.05):
        """Sweep the pan axis across its range and back (a 'looking around').

        Angular rate is step/delay degrees per second (~100 deg/s by default).
        """
        for a in range(low, high + 1, step):
            self.pan = a
            time.sleep(delay)
        for a in range(high, low - 1, -step):
            self.pan = a
            time.sleep(delay)
        self.look_at(pan=90)
