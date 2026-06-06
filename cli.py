"""Minimal CLI to test the ChatterBot head servos.

Examples:
    python cli.py center
    python cli.py pan 120
    python cli.py tilt 60
    python cli.py look 120 70
    python cli.py nod
    python cli.py shake
    python cli.py scan
    python cli.py                  # interactive mode (REPL)

In interactive mode, type the same commands without the "python cli.py" prefix.
Type "help" for the list, "q" or "quit" to exit.
"""

import sys

from chatterbot import HeadController

HELP = """commands:
  center                center both axes (90, 90)
  pan <angle>           set pan axis (0-180)
  tilt <angle>          set tilt axis (0-180)
  look <pan> <tilt>     smooth move to absolute position
  nod                   nod "yes"
  shake                 shake "no"
  scan                  sweep pan left-right-center
  pos                   print current position
  help                  show this help
  q / quit              exit (interactive mode only)"""


def run(head, args):
    """Execute one command. Returns False to signal exit, True otherwise."""
    if not args:
        return True

    cmd, rest = args[0].lower(), args[1:]

    try:
        if cmd in ("q", "quit", "exit"):
            return False
        elif cmd in ("help", "h", "?"):
            print(HELP)
        elif cmd == "center":
            head.center(settle=0)
        elif cmd == "pan":
            head.look_at(pan=float(rest[0]))
        elif cmd == "tilt":
            head.look_at(tilt=float(rest[0]))
        elif cmd == "look":
            head.look_at(pan=float(rest[0]), tilt=float(rest[1]))
        elif cmd == "nod":
            head.nod()
        elif cmd == "shake":
            head.shake()
        elif cmd == "scan":
            head.scan()
        elif cmd == "pos":
            pass  # printed below
        else:
            print(f"unknown command: {cmd!r} (try 'help')")
            return True
    except (IndexError, ValueError):
        print(f"bad arguments for {cmd!r} (try 'help')")
        return True

    print(f"pan={head.pan} tilt={head.tilt}")
    return True


def main(argv):
    head = HeadController(pan_channel=0, tilt_channel=1)

    if argv:
        run(head, argv)
        return

    # Interactive REPL
    print("ChatterBot servo test. Type 'help' for commands, 'q' to quit.")
    while True:
        try:
            line = input("head> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not run(head, line.split()):
            break


if __name__ == "__main__":
    main(sys.argv[1:])
