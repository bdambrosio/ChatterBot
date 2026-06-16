"""Mic driver — bridges the reSpeaker XVF3800 to zenoh.

Two cooperating loops (DESIGN.md §3):

* **control loop** polls the XVF3800 firmware for DoA + VAD and publishes
  ``chatter/voice/event`` with the talker azimuth — ``start`` on the rising edge
  of speech, ``active`` updates while speaking (so the head reflex / gaze can
  track a moving talker), ``stop`` after a hangover of silence.
* **capture loop** reads full-duplex PCM and, while VAD says speech is present,
  publishes VAD-gated binary frames on ``chatter/audio/in`` (see
  ``lib/audio_frame.py`` for the wire format).

No audio processing on the Pi: VAD and DoA come from the XVF3800; the Pi only
gates and ships. Run on the Pi:

    python -m chatterbot.services.mic_driver
"""

import threading
import time

from ..xvf3800 import XVF3800Audio, XVF3800Control
from ..lib import zenoh_helpers as zh
from ..lib.audio_frame import pack_audio_frame
from ..lib.topics import AUDIO_IN, VOICE_EVENT


def _emit(session, vad, doa_deg, confidence):
    zh.publish_json(session, VOICE_EVENT, {
        "ts": zh.now(),
        "vad": vad,                # "start" | "active" | "stop"
        "doa_deg": int(doa_deg),   # 0-359, device frame
        "confidence": confidence,  # coarse: 1.0 speaking, 0.5 hangover, 0.0 stop
    })


def main():
    cfg = zh.load_config()
    ac = cfg.get("audio", {})
    rate = ac.get("sample_rate", 16000)
    channels = ac.get("channels", 2)
    frame_ms = ac.get("frame_ms", 20)
    gated = ac.get("gated", True)
    poll_hz = max(1, ac.get("vad_poll_hz", 25))
    event_hz = max(1, ac.get("voice_event_hz", 15))
    start_frames = max(1, ac.get("vad_start_frames", 2))
    hangover_s = ac.get("vad_hangover_s", 0.6)

    ctrl = XVF3800Control()
    audio = XVF3800Audio(
        capture_device=ac.get("capture_device", "plughw:CARD=Array"),
        playback_device=ac.get("playback_device", "plughw:CARD=Array"),
        sample_rate=rate, channels=channels, frame_ms=frame_ms)
    session = zh.open_session(cfg)

    # Shared between the two loops. `speaking` is the VAD gate; `doa` is the most
    # recent azimuth for tagging audio / events.
    state = {"speaking": False, "doa": 0, "run": True}

    def control_loop():
        consec_speech = 0
        last_speech_t = 0.0
        last_event_t = 0.0
        period = 1.0 / poll_hz
        min_event_gap = 1.0 / event_hz
        while state["run"]:
            t0 = time.time()
            try:
                doa, speech = ctrl.read_doa_vad()
            except Exception as exc:  # transient USB hiccup — keep the loop alive
                print("mic_driver: control read failed:", exc)
                time.sleep(0.2)
                continue
            state["doa"] = doa
            if speech:
                consec_speech += 1
                last_speech_t = t0
            else:
                consec_speech = 0

            if not state["speaking"]:
                if consec_speech >= start_frames:
                    state["speaking"] = True
                    _emit(session, "start", doa, 1.0)
                    last_event_t = t0
            else:
                if (t0 - last_speech_t) >= hangover_s:
                    state["speaking"] = False
                    _emit(session, "stop", doa, 0.0)
                    last_event_t = t0
                elif (t0 - last_event_t) >= min_event_gap:
                    _emit(session, "active", doa, 1.0 if speech else 0.5)
                    last_event_t = t0

            time.sleep(max(0.0, period - (time.time() - t0)))

    def capture_loop():
        seq = 0
        audio.start()
        print(f"mic_driver: capture started ({rate} Hz x{channels}, "
              f"{'VAD-gated' if gated else 'continuous'})")
        while state["run"]:
            frame = audio.read_frame()
            if not frame:
                print("mic_driver: capture EOF (playback keepalive died?) — exiting")
                state["run"] = False
                break
            if gated and not state["speaking"]:
                continue
            zh.publish_bytes(
                session, AUDIO_IN,
                pack_audio_frame(seq, time.time(), rate, channels, frame))
            seq += 1

    ctl_thread = threading.Thread(target=control_loop, daemon=True)
    ctl_thread.start()
    print("mic_driver: ready; voice events ->", VOICE_EVENT)

    try:
        capture_loop()
    except KeyboardInterrupt:
        pass
    finally:
        state["run"] = False
        time.sleep(0.1)
        audio.close()
        session.close()


if __name__ == "__main__":
    main()
