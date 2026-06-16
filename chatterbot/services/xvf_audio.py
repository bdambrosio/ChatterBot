"""xvf_audio — the single duplex owner of the reSpeaker XVF3800.

Merges the old mic_driver with TTS playback (DESIGN.md §3, docs/audio-out-design.md)
so one process owns the device end to end. Four concerns share one zenoh session:

* **playback loop** keeps the XVF3800 speaker stream fed forever — silence when
  idle (this is both the full-duplex capture keepalive and the AEC reference),
  queued TTS PCM when an utterance arrives on ``chatter/audio/out``. Sets
  ``tts_playing`` while draining an utterance.
* **capture loop** publishes VAD-gated binary ``chatter/audio/in`` — but muted
  while ``tts_playing`` (self-voice gating; the mic goes quiet during the bot's
  own speech, on top of the XVF3800's hardware AEC).
* **control loop** polls the XVF3800 for DoA + VAD → ``chatter/voice/event``.
* **audio/out subscriber** enqueues incoming utterance PCM (mono 16 kHz S16_LE
  from ElevenLabs ``pcm_16000``) for the playback loop.

No audio processing on the Pi: VAD/DoA come from firmware; TTS is synthesized on
the CW side. Run on the Pi:

    python -m chatterbot.services.xvf_audio
"""

import threading
import time
from array import array

from ..xvf3800 import XVF3800Audio, XVF3800Control
from ..lib import zenoh_helpers as zh
from ..lib.audio_frame import pack_audio_frame, unpack_audio_frame
from ..lib.topics import AUDIO_IN, AUDIO_OUT, VOICE_EVENT


def _mono_to_stereo(mono):
    """Duplicate each 16-bit sample into both channels (mono -> interleaved 2ch)."""
    samples = array("h")
    samples.frombytes(mono)
    out = array("h", bytes(len(mono) * 2))
    out[0::2] = samples
    out[1::2] = samples
    return out.tobytes()


def _emit(session, vad, doa_deg, confidence):
    zh.publish_json(session, VOICE_EVENT, {
        "ts": zh.now(),
        "vad": vad,                # "start" | "active" | "stop"
        "doa_deg": int(doa_deg),
        "confidence": confidence,
    })


def main():
    cfg = zh.load_config()
    ac = cfg.get("audio", {})
    rate = ac.get("sample_rate", 16000)
    channels = ac.get("channels", 2)         # device capture/playback channels
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

    state = {"speaking": False, "tts_playing": False, "run": True}
    play_buf = bytearray()                   # pending mono TTS PCM
    play_lock = threading.Lock()

    chunk_mono = int(rate * 2 * frame_ms / 1000)   # mono bytes per playback chunk
    silence_stereo = bytes(chunk_mono * 2)         # one chunk of 2ch silence

    def on_audio_out(_key, payload):
        try:
            hdr, pcm = unpack_audio_frame(payload)
        except ValueError as exc:
            print("xvf_audio: bad audio/out frame:", exc)
            return
        with play_lock:
            play_buf.extend(pcm)
        print(f"xvf_audio: queued utterance seq={hdr['seq']} "
              f"{len(pcm)}B (~{len(pcm) / 2 / rate:.1f}s)")

    def playback_loop():
        # Feed the speaker forever; aplay back-pressure paces this to real time.
        while state["run"]:
            with play_lock:
                if play_buf:
                    chunk = bytes(play_buf[:chunk_mono])
                    del play_buf[:chunk_mono]
                else:
                    chunk = b""
            if chunk:
                state["tts_playing"] = True
                if len(chunk) < chunk_mono:           # pad final partial chunk
                    chunk += bytes(chunk_mono - len(chunk))
                ok = audio.write_playback(_mono_to_stereo(chunk))
            else:
                state["tts_playing"] = False
                ok = audio.write_playback(silence_stereo)
            if not ok:
                print("xvf_audio: playback stream died — exiting")
                state["run"] = False
                break

    def control_loop():
        consec_speech = 0
        last_speech_t = 0.0
        last_event_t = 0.0
        period = 1.0 / poll_hz
        min_event_gap = 1.0 / event_hz
        while state["run"]:
            t0 = time.time()
            # Don't react to / publish the bot's own voice while it speaks.
            if state["tts_playing"]:
                consec_speech = 0
                state["speaking"] = False
                time.sleep(period)
                continue
            try:
                doa, speech = ctrl.read_doa_vad()
            except Exception as exc:
                print("xvf_audio: control read failed:", exc)
                time.sleep(0.2)
                continue
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
        while state["run"]:
            frame = audio.read_frame()
            if not frame:
                print("xvf_audio: capture EOF — exiting")
                state["run"] = False
                break
            if state["tts_playing"]:        # self-voice gating
                continue
            if gated and not state["speaking"]:
                continue
            zh.publish_bytes(
                session, AUDIO_IN,
                pack_audio_frame(seq, time.time(), rate, channels, frame))
            seq += 1

    audio.start()
    zh.declare_subscriber_bytes(session, AUDIO_OUT, on_audio_out)
    threading.Thread(target=playback_loop, daemon=True).start()
    threading.Thread(target=control_loop, daemon=True).start()
    print(f"xvf_audio: ready ({rate} Hz) — voice events -> {VOICE_EVENT}, "
          f"playing {AUDIO_OUT}")

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
