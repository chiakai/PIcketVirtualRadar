#!/bin/sh
set -eu

APP_DIR=/opt/picket-virtual-radar
CONFIG_DIR=/etc/picket-virtual-radar
SERVICE_FILE=/etc/systemd/system/picket-virtual-radar.service
APP_USER=${PVR_USER:-rpi}
JOURNAL_DIR=/etc/systemd/journald.conf.d

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if systemctl is-active --quiet picket-virtual-radar.service; then
    systemctl stop picket-virtual-radar.service
fi

install -d -m 0755 "$APP_DIR" "$CONFIG_DIR"
install -d -m 0755 "$APP_DIR/tools"
install -d -m 0755 /usr/lib/picket-virtual-radar
cp "$SCRIPT_DIR/pyproject.toml" "$APP_DIR/pyproject.toml"
rm -rf "$APP_DIR/src"
cp -R "$SCRIPT_DIR/src" "$APP_DIR/src"
if [ -d "$SCRIPT_DIR/tools" ]; then
    cp -R "$SCRIPT_DIR/tools/." "$APP_DIR/tools/"
    chmod 0755 "$APP_DIR/tools/readonly_root.sh" "$APP_DIR/tools/test_config_power_loss.py"
fi
install -m 0755 "$SCRIPT_DIR/tools/set_display_rotation.sh" \
    /usr/lib/picket-virtual-radar/set-display-rotation

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    install -m 0600 -o "$APP_USER" -g "$APP_USER" \
        "$SCRIPT_DIR/config.example.json" "$CONFIG_DIR/config.json"
fi
chown "$APP_USER:$APP_USER" "$CONFIG_DIR/config.json"
chmod 0600 "$CONFIG_DIR/config.json"
chown "$APP_USER:$APP_USER" "$CONFIG_DIR"
chmod 0700 "$CONFIG_DIR"

# Raspberry Pi OS supplies lgpio as a system package. Make it visible inside
# the application venv while keeping Python application dependencies isolated.
python3 -m venv --system-site-packages "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install "$APP_DIR"

# Keep the PiTFT framebuffer orientation aligned with the configured touch
# transform. Preserve the current 90/270 selection across reinstalls.
BOOT_CONFIG=/boot/firmware/config.txt
if [ ! -f "$BOOT_CONFIG" ]; then
    BOOT_CONFIG=/boot/config.txt
fi
if [ -f "$BOOT_CONFIG" ] && grep -q '^dtoverlay=pitft28-capacitive,' "$BOOT_CONFIG"; then
    ROTATION=$(PVR_CONFIG="$CONFIG_DIR/config.json" "$APP_DIR/.venv/bin/python" -c \
        'from picket_virtual_radar.config import load_config; print(load_config().touch.rotation)')
    /usr/lib/picket-virtual-radar/set-display-rotation "$ROTATION"
fi
install -m 0644 "$SCRIPT_DIR/systemd/picket-virtual-radar.service" "$SERVICE_FILE"
install -m 0644 "$SCRIPT_DIR/systemd/picket-display-rotate@.service" \
    /etc/systemd/system/picket-display-rotate@.service
if [ -d /etc/polkit-1/rules.d ]; then
    install -m 0644 "$SCRIPT_DIR/systemd/49-picket-virtual-radar.rules" \
        /etc/polkit-1/rules.d/49-picket-virtual-radar.rules
    if [ "${PVR_INSTALL_DEVICE_POLKIT:-}" = "YES" ]; then
        install -m 0644 "$SCRIPT_DIR/systemd/50-picket-device-control.rules" \
            /etc/polkit-1/rules.d/50-picket-device-control.rules
    fi
fi
install -d -m 0755 "$JOURNAL_DIR"
install -m 0644 "$SCRIPT_DIR/systemd/10-picket-virtual-radar-journal.conf" \
    "$JOURNAL_DIR/10-picket-virtual-radar.conf"

systemctl daemon-reload
systemctl restart systemd-journald.service
systemctl enable picket-virtual-radar.service
systemctl restart picket-virtual-radar.service
systemctl --no-pager --full status picket-virtual-radar.service
