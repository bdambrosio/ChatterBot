"""Binary framing for the ``chatter/audio/in`` / ``chatter/audio/out`` streams.

PCM audio is shipped as a **raw binary zenoh payload** (not base64-in-JSON; see
DESIGN.md §4): a fixed 24-byte little-endian header followed by interleaved PCM
samples. The header carries a sequence number (so a consumer detects drops) and
a capture timestamp, plus enough format info to decode without out-of-band
config.

Header layout (``<4sBBBBIId`` = 24 bytes), then PCM bytes:

    offset size field
    0      4    magic        b"CBA1"
    4      1    version      1
    5      1    format       0 = S16_LE  (see FMT_*)
    6      1    channels     e.g. 2
    7      1    (reserved)   0
    8      4    sample_rate  uint32, e.g. 16000
    12     4    seq          uint32, monotonic per stream, wraps at 2^32
    20     8    ts           float64 unix epoch seconds at capture

Consumers in other projects (e.g. Cognitive_workbench) reproduce this from the
spec — see docs/cw-voice-sensor.md.
"""

import struct

MAGIC = b"CBA1"
VERSION = 1

# Sample formats
FMT_S16LE = 0

_HDR = "<4sBBBBIId"
HEADER_SIZE = struct.calcsize(_HDR)  # 24


def pack_audio_frame(seq, ts, sample_rate, channels, pcm, fmt=FMT_S16LE):
    """Pack one PCM frame with its header into a single bytes payload."""
    header = struct.pack(
        _HDR, MAGIC, VERSION, fmt, channels, 0,
        int(sample_rate), seq & 0xFFFFFFFF, float(ts),
    )
    return header + pcm


def unpack_audio_frame(payload):
    """Inverse of :func:`pack_audio_frame`. Returns ``(header_dict, pcm_bytes)``."""
    if len(payload) < HEADER_SIZE:
        raise ValueError("audio frame shorter than header")
    magic, ver, fmt, channels, _reserved, sample_rate, seq, ts = struct.unpack(
        _HDR, payload[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError("bad audio frame magic %r" % magic)
    header = {
        "version": ver,
        "format": fmt,
        "channels": channels,
        "sample_rate": sample_rate,
        "seq": seq,
        "ts": ts,
    }
    return header, payload[HEADER_SIZE:]
