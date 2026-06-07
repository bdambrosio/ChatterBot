"""Pi-side process launcher.

Starts the head and camera services and restarts any that exit, with
exponential backoff. Lightweight version of Body's launcher. Run on the Pi
(after `zenohd` is running):

    python -m chatterbot.launcher
"""

import signal
import subprocess
import sys
import time

SERVICES = [
    ("head_service", [sys.executable, "-m", "chatterbot.services.head_service"]),
    ("camera_service", [sys.executable, "-m", "chatterbot.services.camera_service"]),
]

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0


def main():
    procs = {}        # name -> Popen
    backoff = {}      # name -> current backoff seconds
    next_start = {}   # name -> earliest restart time

    for name, _ in SERVICES:
        backoff[name] = BACKOFF_START_S
        next_start[name] = 0.0

    stopping = {"flag": False}

    def shutdown(*_):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("launcher: starting", ", ".join(n for n, _ in SERVICES))
    try:
        while not stopping["flag"]:
            now = time.time()
            for name, cmd in SERVICES:
                proc = procs.get(name)
                if proc is None or proc.poll() is not None:
                    if proc is not None:
                        # It died — back off before relaunch.
                        print(f"launcher: {name} exited ({proc.returncode}); "
                              f"restart in {backoff[name]:.0f}s")
                        next_start[name] = now + backoff[name]
                        backoff[name] = min(BACKOFF_MAX_S, backoff[name] * 2)
                        procs[name] = None
                    if now >= next_start[name]:
                        procs[name] = subprocess.Popen(cmd)
                        print(f"launcher: started {name} (pid {procs[name].pid})")
                        # Reset backoff once it has survived a bit.
                        backoff[name] = BACKOFF_START_S
            time.sleep(0.5)
    finally:
        print("launcher: shutting down")
        for name, proc in procs.items():
            if proc and proc.poll() is None:
                proc.terminate()
        for name, proc in procs.items():
            if proc:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()
