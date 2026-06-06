"""ChatterBot entry point — a quick demo of the head's movements."""

import time

from chatterbot import HeadController


def main():
    head = HeadController(pan_channel=0, tilt_channel=1)

    print("Centering...")
    head.center()

    print("Looking around...")
    head.scan()

    print("Nodding yes...")
    head.nod()
    time.sleep(0.5)

    print("Shaking no...")
    head.shake()
    time.sleep(0.5)

    print("Looking up and to the left...")
    head.look_at(pan=130, tilt=60)
    time.sleep(1)

    print("Back to center.")
    head.center()


if __name__ == "__main__":
    main()
