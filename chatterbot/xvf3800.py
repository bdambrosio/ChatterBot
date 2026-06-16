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
    """Full-duplex ALSA audio for the XVF3800 via ``arecord``/``aplay``.

    Capture: ``read_frame()`` yields fixed-size raw PCM frames from ``arecord``.
    Playback: a persistent ``aplay`` reads raw PCM from **stdin** — the caller
    feeds it continuously (silence when idle, TTS when speaking). That open
    playback stream is what lets the capture endpoint stream at all (the XVF3800
    clocks capture off playback for AEC; capture-alone EIOs), and it doubles as
    the AEC loudspeaker reference. Subprocesses keep the Pi free of an ALSA
    binding dep and match the verified manual pipeline.
    """

    def __init__(self, capture_device="plughw:CARD=Array",
                 playback_device="plughw:CARD=Array",
                 sample_rate=16000, channels=2, frame_ms=20,
                 card="Array", playback_volume_pct=None):
        self.capture_device = capture_device
        self.playback_device = playback_device
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.card = card
        self.playback_volume_pct = playback_volume_pct
        self.frame_bytes = int(sample_rate * channels * 2 * frame_ms / 1000)
        self._cap = None
        self._play = None

    def start(self):
        # Set the device output level (the XVF3800 boots at ~-23 dB, which is too
        # quiet). No sudo needed for the mixer. Volatile across reboots, so we set
        # it on every start rather than relying on a saved alsactl state.
        if self.playback_volume_pct is not None:
            subprocess.run(
                ["amixer", "-c", self.card, "sset", "PCM",
                 f"{self.playback_volume_pct}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

        common = ["-f", "S16_LE", "-c", str(self.channels), "-r", str(self.sample_rate)]
        # Persistent playback reading raw PCM from stdin. A small buffer keeps the
        # idle-silence backlog short so queued TTS starts promptly; aplay blocks
        # our writes when full, which paces the writer to real time.
        self._play = subprocess.Popen(
            ["aplay", "-q", "-D", self.playback_device, *common, "-t", "raw",
             "--buffer-time", "200000", "--period-time", "20000"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Prime the playback buffer with ~150 ms of silence so the DAC clock is
        # running before capture opens — capture EIOs without an active playback
        # clock (the AEC full-duplex coupling).
        self.write_playback(bytes(int(self.sample_rate * 0.15) * self.channels * 2))
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

    def write_playback(self, data):
        """Write one chunk of interleaved ``channels``-ch PCM to the speaker.

        Blocks when aplay's buffer is full (real-time back-pressure). Returns
        False if the playback stream has died.
        """
        try:
            self._play.stdin.write(data)
            self._play.stdin.flush()
            return True
        except (BrokenPipeError, ValueError):
            return False

    def close(self):
        if self._play and self._play.stdin:
            try:
                self._play.stdin.close()
            except (BrokenPipeError, ValueError):
                pass
        for proc in (self._cap, self._play):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
