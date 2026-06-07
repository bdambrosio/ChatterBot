"""ChatterBot — a Raspberry Pi companion bot head."""

__version__ = "0.1.0"

__all__ = ["HeadController"]


def __getattr__(name):
    # Lazy so importing shared bits (chatterbot.lib.topics) off-bot doesn't pull
    # in adafruit_servokit, which is only installed on the Pi.
    if name == "HeadController":
        from .head import HeadController
        return HeadController
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
