#!/bin/sh
set -eu

case "${1:-status}" in
    status)
        raspi-config nonint get_overlay_now
        ;;
    enable)
        if [ "${PVR_ENABLE_READ_ONLY_ROOT:-}" != "YES" ]; then
            echo "Refusing to enable overlay root without PVR_ENABLE_READ_ONLY_ROOT=YES." >&2
            echo "Web setting changes will not survive reboot unless /etc/picket-virtual-radar is moved to writable storage." >&2
            exit 2
        fi
        raspi-config nonint enable_overlayfs
        echo "Overlay root requested. Reboot is required."
        ;;
    disable)
        raspi-config nonint disable_overlayfs
        echo "Overlay root disable requested. Reboot is required."
        ;;
    *)
        echo "usage: $0 status|enable|disable" >&2
        exit 2
        ;;
esac
