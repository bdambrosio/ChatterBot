#!/usr/bin/env bash
# Turn the reSpeaker XVF3800 LED ring off at night (20:00-06:00 local), restore by day.
# Decides from the current hour so it's correct even after a midday/midnight reboot.
# Pi runs on local time. See deploy/README.md for cron install.
#
# NOTE: we switch LED_EFFECT, not LED_BRIGHTNESS. The device runs DoA mode
# (LED_EFFECT 4) by default, and LED_BRIGHTNESS only applies to breath/rainbow
# modes -- it is a no-op in DoA, so brightness writes silently did nothing.
# Effect enum: 0=off  1=breath  2=rainbow  3=single-color  4=doa
DIR="$HOME/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit"
NIGHT=0   # off
DAY=4     # doa (direction-of-arrival listening animation)
H=$((10#$(date +%H)))   # strip leading zero so 08 isn't parsed as octal
if [ "$H" -ge 20 ] || [ "$H" -lt 6 ]; then E=$NIGHT; else E=$DAY; fi
cd "$DIR" || exit 1      # xvf_host needs libcommand_map.so + transport_config.yaml in cwd
./xvf_host led_effect "$E" >>"$HOME/xvf_led.log" 2>&1
echo "$(date '+%F %T') set led_effect=$E (hour=$H)" >>"$HOME/xvf_led.log"
