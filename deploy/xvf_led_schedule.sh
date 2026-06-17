#!/usr/bin/env bash
# Dim the reSpeaker XVF3800 LED ring at night (20:00-06:00 local), restore by day.
# Decides from the current hour so it's correct even after a midday/midnight reboot.
# Pi runs on local time. See deploy/README.md for cron install.
DIR="$HOME/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit"
NIGHT=2
DAY=127
H=$((10#$(date +%H)))   # strip leading zero so 08 isn't parsed as octal
if [ "$H" -ge 20 ] || [ "$H" -lt 6 ]; then B=$NIGHT; else B=$DAY; fi
cd "$DIR" || exit 1      # xvf_host needs libcommand_map.so + transport_config.yaml in cwd
./xvf_host led_brightness "$B" >>"$HOME/xvf_led.log" 2>&1
echo "$(date '+%F %T') set led_brightness=$B (hour=$H)" >>"$HOME/xvf_led.log"
