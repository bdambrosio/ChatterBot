"""Pi Camera Module 3 still capture (libcamera / picamera2).

Pi-side only. picamera2 is imported lazily so the rest of the package (and the
desktop) can import ``chatterbot`` on machines without the camera stack.

On Raspberry Pi OS install picamera2 via apt, not pip:
    sudo apt install -y python3-picamera2
"""

from io import BytesIO


class CameraCapture:
    """Captures JPEG stills on demand from the Pi camera.

    Args:
        width, height: capture resolution.
        quality: JPEG quality 1-100.
        hflip, vflip: mirror the image (mount-dependent).
    """

    def __init__(self, width=1280, height=720, quality=85, hflip=False, vflip=False):
        from picamera2 import Picamera2
        from libcamera import Transform

        self.width = width
        self.height = height
        self.quality = quality

        self._picam2 = Picamera2()
        config = self._picam2.create_still_configuration(
            main={"size": (width, height)},
            transform=Transform(hflip=int(hflip), vflip=int(vflip)),
        )
        self._picam2.configure(config)
        self._picam2.options["quality"] = quality
        self._picam2.start()

    def capture_jpeg(self):
        """Capture a single frame and return JPEG-encoded bytes."""
        buf = BytesIO()
        self._picam2.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def close(self):
        try:
            self._picam2.stop()
        except Exception:
            pass
