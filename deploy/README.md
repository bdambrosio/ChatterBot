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

Manually:

```bash
python -m chatterbot.launcher
```

Or as a service (starts after `zenohd`, comes up on boot):

```bash
sudo cp deploy/chatterbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chatterbot
```

`chatterbot.service` runs with the system Python (`/usr/bin/python3`) so the
apt-installed `picamera2` is visible. If you use a venv, create it with
`--system-site-packages` and edit `ExecStart` to point at that venv's python.
Adjust `WorkingDirectory`/`User` if your checkout path or user differs.
