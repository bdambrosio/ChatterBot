# Deploy

## Zenoh router (`zenohd`)

`zenohd` is the standalone zenoh **router** daemon — a separate prebuilt binary,
*not* the `eclipse-zenoh` pip package (that's only the client library). All
ChatterBot processes connect to it on `tcp/...:7447`.

### Install (Raspberry Pi)

If you already ran the Body project on this Pi, the binary is probably at
`~/zenoh/<version>/zenohd` — reuse it.

Otherwise download it (match the version to your `eclipse-zenoh` python lib:
`python -c "import zenoh; print(zenoh.__version__)"`):

```bash
mkdir -p ~/zenoh && cd ~/zenoh
# aarch64 = 64-bit Raspberry Pi OS (use armv7 asset for 32-bit; check `uname -m`)
wget https://github.com/eclipse-zenoh/zenoh/releases/download/1.9.0/zenoh-1.9.0-aarch64-unknown-linux-gnu-standalone.zip
unzip zenoh-1.9.0-aarch64-unknown-linux-gnu-standalone.zip -d 1.9.0
chmod +x 1.9.0/zenohd
```

### Run

Manually (bare `zenohd` already defaults to router mode on `tcp/[::]:7447`):

```bash
~/zenoh/1.9.0/zenohd -c deploy/zenohd-router.json
```

Or as a service (edit paths in `zenohd.service` first):

```bash
sudo cp deploy/zenohd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zenohd
```

## ChatterBot services (`chatterbot.launcher`)

The launcher starts the head + camera services and restarts any that die. It
needs the zenoh router up first.

First create the venv (once). Use `--system-site-packages` so the apt-installed
`picamera2` stays visible — it is not a pip package:

```bash
cd ~/Documents/Projects/ChatterBot
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-pi.txt
```

Run manually:

```bash
.venv/bin/python -m chatterbot.launcher
```

Or as a service (starts after `zenohd`, comes up on boot):

```bash
sudo cp deploy/chatterbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chatterbot
```

`chatterbot.service` runs from `.venv/bin/python`. If you installed the deps
into the system Python instead, edit `ExecStart` to `/usr/bin/python3`. Adjust
`WorkingDirectory`/`User` if your checkout path or user differs.

## XVF3800 LED ring night dimming (`xvf_led_schedule.sh`)

Turns the mic array's LED ring **off** overnight (20:00–06:00 local) and restores
DoA mode by day. It drives the LEDs through the prebuilt `xvf_host` tool from the
upstream respeaker repo (expected at
`~/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit/`), which coexists
fine with the running audio service. The script picks the state from the current
hour, so a reboot at any time lands correctly.

It switches `LED_EFFECT` (`0=off … 4=doa`), **not** `LED_BRIGHTNESS`. The device
runs DoA mode by default, and `LED_BRIGHTNESS` only applies to breath/rainbow
modes — it's a silent no-op in DoA, so brightness writes never dimmed anything.
To keep DoA but dimmer instead of fully off, lower `LED_DOA_COLOR` at night
(e.g. `0x000810`) and restore `0x002040` by day.

Edit `NIGHT`/`DAY` in the script to change the effect. Then install:

```bash
install -Dm755 deploy/xvf_led_schedule.sh ~/bin/xvf_led_schedule.sh
( crontab -l 2>/dev/null | grep -v xvf_led_schedule.sh
  echo '0 6 * * *  /home/bruce/bin/xvf_led_schedule.sh'
  echo '0 20 * * * /home/bruce/bin/xvf_led_schedule.sh'
  echo '@reboot sleep 45 && /home/bruce/bin/xvf_led_schedule.sh'
) | crontab -
```

Runs are logged to `~/xvf_led.log`. For a fully-dark ring (rather than very
dim), swap the `led_brightness` call for `led_effect 0` (off) / `led_effect 4`
(restore DoA mode).
