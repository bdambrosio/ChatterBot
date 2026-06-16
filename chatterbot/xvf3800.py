"""reSpeaker XVF3800 USB 4-Mic Array — driver wrapper for ChatterBot.

The XVF3800 needs **no kernel driver**: its audio is UAC2 class-compliant (ALSA
binds it automatically as card "Array") and its control channel is plain USB
vendor requests. This module wraps the two facilities ``mic_driver`` needs:

* :class:`XVF3800Control` — read Direction-of-Arrival and VAD over USB vendor
  control transfers. A single ``DOA_VALUE`` read returns **both**: the dominant
  talker azimuth (0-359°) and a speech-present flag. Needs a udev rule for
  non-root USB access — see docs/xvf3800-setup.md.

* :class:`XVF3800Audio` — full-duplex ALSA capture. **CRITICAL:** the capture
  stream only delivers samples while a playback stream is *also* open — the chip
  clocks capture off playback for its AEC. Capture-alone returns ``EIO``. So this
  helper holds a silence playback stream open as a keepalive.

Verified on the ChatterBot Pi (2026-06-16): USB id 2886:001a, card "Array",
S16_LE / 2 channels / 16 kHz; DoA confirmed live.
"""

import struct
import subprocess
import time

import usb.core
import usb.util
import libusb_package

VENDOR_ID = 0x2886
PRODUCT_ID = 0x001A

# Firmware control-channel status codes (response byte 0).
CONTROL_SUCCESS = 0
SERVICER_COMMAND_RETRY = 64

# Vendor IN request to the device's control endpoint.
_RT_IN = usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE

# DOA_VALUE: resid 20, cmdid 18 -> two uint16: [doa_deg 0-359, speech 0|1].
_DOA_RESID, _DOA_CMDID, _DOA_NVALS = 20, 18, 2


class XVF3800Error(RuntimeError):
    pass


class XVF3800Control:
    """Reads DoA + VAD from the XVF3800 over USB vendor control transfers."""

    def __init__(self, timeout_ms=1000, max_retry=100):
        dev = libusb_package.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise XVF3800Error(
                "XVF3800 not found on USB (expected 2886:001a; check the cable "
                "and `lsusb`)")
        self.dev = dev
        self.timeout_ms = timeout_ms
        self.max_retry = max_retry

    def _read_uint16(self, resid, cmdid, nvals):
        wlength = nvals * 2 + 1  # +1 leading status byte
        for _ in range(self.max_retry):
            resp = self.dev.ctrl_transfer(
                _RT_IN, 0, 0x80 | cmdid, resid, wlength, self.timeout_ms)
            status = resp[0]
            if status == CONTROL_SUCCESS:
                return struct.unpack("<%dH" % nvals, resp.tobytes()[1:1 + nvals * 2])
            if status != SERVICER_COMMAND_RETRY:
                raise XVF3800Error("control read status %d" % status)
            time.sleep(0.01)
        raise XVF3800Error("control read exceeded %d retries" % self.max_retry)

    def read_doa_vad(self):
        """Return ``(doa_deg, speech)``.

        ``doa_deg`` is the dominant talker azimuth 0-359° in the device frame;
        ``speech`` is a bool (the XVF3800's own VAD). One USB round-trip.
        """
        doa, speech = self._read_uint16(_DOA_RESID, _DOA_CMDID, _DOA_NVALS)
        return doa, bool(speech)


class XVF3800Audio:
    """Full-duplex ALSA capture from the XVF3800 via ``arecord``/``aplay``.

    Opens a silence playback keepalive (``aplay /dev/zero``) so the capture
    endpoint actually streams, then yields fixed-size raw PCM frames from
    ``arecord``. Using subprocesses keeps the Pi free of an ALSA binding dep and
    matches the verified manual pipeline.
    """

    def __init__(self, capture_device="plughw:CARD=Array",
                 playback_device="plughw:CARD=Array",
                 sample_rate=16000, channels=2, frame_ms=20):
        self.capture_device = capture_device
        self.playback_device = playback_device
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.frame_bytes = int(sample_rate * channels * 2 * frame_ms / 1000)
        self._cap = None
        self._play = None

    def start(self):
        common = ["-f", "S16_LE", "-c", str(self.channels), "-r", str(self.sample_rate)]
        # Silence keepalive: without an open playback stream the capture endpoint
        # returns EIO (the XVF3800 clocks capture off playback for AEC).
        self._play = subprocess.Popen(
            ["aplay", "-q", "-D", self.playback_device, *common, "/dev/zero"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._cap = subprocess.Popen(
            ["arecord", "-q", "-D", self.capture_device, *common, "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read_frame(self):
        """Block for one full PCM frame. Returns ``b""`` on EOF (stream died)."""
        buf = bytearray()
        while len(buf) < self.frame_bytes:
            chunk = self._cap.stdout.read(self.frame_bytes - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return bytes(buf)

    def close(self):
        for proc in (self._cap, self._play):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
