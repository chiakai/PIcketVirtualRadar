#!/bin/sh
set -eu

rotation=${1:-}
case "$rotation" in
    90|270) ;;
    *) echo "rotation must be 90 or 270" >&2; exit 2 ;;
esac

boot_config=/boot/firmware/config.txt
if [ ! -f "$boot_config" ]; then
    boot_config=/boot/config.txt
fi
if [ ! -f "$boot_config" ]; then
    echo "Raspberry Pi boot config was not found" >&2
    exit 3
fi
if ! grep -q '^dtoverlay=pitft28-capacitive,' "$boot_config"; then
    echo "pitft28-capacitive overlay was not found" >&2
    exit 4
fi

backup="$boot_config.pvr-rotation-backup"
temporary="$boot_config.pvr-rotation-tmp"
cp -p "$boot_config" "$backup"
sed -E "/^dtoverlay=pitft28-capacitive,/ s/rotate=(90|270)/rotate=$rotation/" \
    "$boot_config" > "$temporary"
if cmp -s "$boot_config" "$temporary" && ! grep -q "^dtoverlay=pitft28-capacitive,.*rotate=$rotation" "$temporary"; then
    rm -f "$temporary"
    echo "PiTFT overlay does not contain a replaceable rotate option" >&2
    exit 5
fi
chmod --reference="$boot_config" "$temporary"
chown --reference="$boot_config" "$temporary"
mv "$temporary" "$boot_config"
