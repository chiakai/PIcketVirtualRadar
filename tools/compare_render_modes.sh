#!/bin/bash
set -u

APP=/opt/picket-virtual-radar/.venv/bin/picket-virtual-radar

restart_service() {
    sudo -n systemctl start picket-virtual-radar.service
}

trap restart_service EXIT INT TERM
sudo -n systemctl stop picket-virtual-radar.service

echo "-- full frame --"
TIMEFORMAT='real_seconds=%R user_seconds=%U system_seconds=%S'
time PVR_CONFIG=/tmp/config.full.json timeout --signal=TERM --kill-after=3 10 "$APP"

echo "-- dirty rectangles --"
time PVR_CONFIG=/tmp/config.dirty.json timeout --signal=TERM --kill-after=3 10 "$APP"
