"""ChatterBot zenoh topic (key expression) names.

Single source of truth for the `chatter/...` namespace described in DESIGN.md.
"""

# Desktop -> Pi
HEAD_CMD = "chatter/head/cmd"          # {ts, pan?, tilt?, gesture?, smooth?}
HEAD_MODE = "chatter/head/mode"        # {ts, doa_follow}
CAMERA_CAPTURE = "chatter/camera/capture"  # {ts, request_id, width?, height?}
HEARTBEAT = "chatter/heartbeat"        # {ts, seq}

# Pi -> Desktop
HEAD_STATUS = "chatter/head/status"    # {ts, pan, tilt, state, mode}
CAMERA_IMAGE = "chatter/camera/image"  # {ts, request_id, format, data_base64, ...}
STATUS = "chatter/status"              # {ts, processes, ...}

# Audio (XVF3800)
VOICE_EVENT = "chatter/voice/event"    # {ts, vad: start|active|stop, doa_deg, confidence}
AUDIO_IN = "chatter/audio/in"          # binary: audio_frame header + S16_LE PCM (VAD-gated)
AUDIO_OUT = "chatter/audio/out"        # binary: audio_frame header + S16_LE PCM (TTS, future)
