# PIcket Virtual Radar

A Raspberry Pi 3 implementation of the core Pocket Virtual Radar experience using an Adafruit 2.8-inch PiTFT Plus capacitive touchscreen. This is not a direct port of the original ESP32 project. It is a redesign for Raspberry Pi OS Lite, a 320×240 landscape display, Linux networking, and long-running appliance operation.

[繁體中文說明](README.md)

## Goals and design

- Boot directly into a full-screen radar without a desktop environment.
- Present aircraft clearly in a 240×240 radar area plus an 80-pixel information panel.
- Use the OpenSky OAuth2 API without terminating the display when the API or network fails.
- Provide simple finger-friendly controls for a capacitive touchscreen.
- Offer a mobile Web configuration page so no keyboard is required.
- Start a setup access point when no known Wi-Fi is available, with failure recovery and a physical reset button.
- Use systemd, a watchdog, atomic configuration writes, and last-known-good rollback for appliance-style reliability.

## Hardware and operating system

- Raspberry Pi 3
- [Adafruit PiTFT Plus 320×240 2.8" TFT + Capacitive Touchscreen, Product ID 2423](https://www.adafruit.com/product/2423)
- 64-bit Raspberry Pi OS Lite
- Optional USB GPS dongle producing standard NMEA 0183 GGA or RMC data
- Display: 320×240 RGB565
- Touch device name: `EP0110M09`
- Landscape overlay rotation: `rotate=90` by default, switchable to `270°` from the Web UI
- Backlight: BCM GPIO 18, 1 kHz PWM
- Wi-Fi reset button: BCM GPIO 17
- Safe-shutdown button: BCM GPIO 22
- Help button: BCM GPIO 27

The capacitive PiTFT may not expose `/sys/class/backlight`; brightness is still controllable through GPIO 18 PWM. The default is 80%, and the Web UI supports 10–100% in 5% steps.

## Architecture

```text
OpenSky OAuth2 / states API
            │
            ▼
     OpenSky data layer ── timeout / backoff / last good snapshot
            │
            ▼
     ICAO24 tracking ── interpolation / short prediction / expiry
            │
            ▼
  320×240 Pygame renderer ── RGB565 ── /dev/fb0
            │
     ┌──────┴──────┐
 capacitive touch   Web settings
                         │
                   NetworkManager
```

Main modules under `src/picket_virtual_radar/`:

- `app.py`: main loop, touch actions, and component coordination.
- `radar_renderer.py`: radar, side panel, overlays, and QR code.
- `opensky.py`: OAuth2 token handling, API validation, backoff, and caching.
- `tracking.py`: aircraft state, interpolation, prediction, and expiry.
- `gps.py`: USB serial discovery, NMEA checksum/GGA/RMC parsing, and fix timeout.
- `wifi_manager.py`: client reconnect, AP fallback, SSID scanning, and button reset.
- `web_server.py`: token-protected Web settings.
- `settings_store.py` and `config_recovery.py`: atomic settings and rollback.
- `system_health.py`: systemd watchdog notification, thermal/power monitoring, and safe shutdown.

## Boot behavior

`picket-virtual-radar.service` is enabled at boot:

```text
Raspberry Pi OS starts
→ PiTFT framebuffer and touch drivers load
→ systemd starts the radar service
→ backlight, touch, Wi-Fi manager, Web, and OpenSky start
→ full-screen radar appears
```

The radar still starts when the network or OpenSky is unavailable. The service uses `Type=notify`, a 30-second watchdog, and `Restart=always` so both hangs and clean process exits recover automatically.

## Display layout

The screen is split into a 240×240 radar area and an 80×240 aircraft information panel.

### Radar area

The radar contains:

- Three concentric range circles.
- Cardinal directions and 30-degree bearing marks.
- An optional green sweep line.
- Aircraft positions, callsigns, and heading-oriented symbols.
- Up to three priority flights can be configured on the Web UI; matching symbols, heading markers, and callsigns turn red.
- A cyan selection circle around the selected aircraft.
- A latitude-aware geographic projection that corrects east-west scale.

Information outside the circular sweep area:

- Top left: `PIcket RADAR`.
- Top right: right-aligned `STATUS`, representing device network state.
- Bottom left: `WiFi` with six signal boxes; active boxes are filled bright green. It changes to `Ethernet` only when Ethernet has an IPv4 address and default route.
- Bottom right: right-aligned `RANGE` and current display radius.

Possible `STATUS` values:

- `ONLINE`: usable Wi-Fi or Ethernet.
- `AP`: setup hotspot is active.
- `CONNECTING`: switching Wi-Fi networks.
- `DISCONNECTED`: no usable network yet.

### Range display zoom

Double-tap the bottom-right Range area to toggle between the full configured display radius and 50%. For a configured radius of 50 km, the display switches between 50 km and 25 km.

This changes only rendering and which aircraft are visible on screen. The OpenSky bounding box and API request radius remain at the configured 50 km. Zoom is not persisted and returns to full range after a service restart.

### AIRCRAFT side panel

The top of the right panel shows:

- `AIRCRAFT` and the number currently visible.
- Selected callsign or ICAO24.
- Heading.
- Altitude and speed in the configured units.
- Data age.

Data-age formats:

- `A:3s`: Actual; the last real position is approximately 3 seconds old.
- `P:12s`: Predicted; the shown position is extrapolated from the last speed and heading, whose source data is approximately 12 seconds old.

The bottom line shows OpenSky API state:

- Green `API OK`: successful update.
- Yellow `API CONFIG`: OAuth credentials are missing.
- Yellow `API RATE`: OpenSky rate limit.
- Red `API AUTH`: invalid Client ID, Client Secret, or token.
- Red `API ERROR`: network, timeout, HTTP, JSON, or another API error.

`STATUS` and `API` are independent. With working networking but invalid credentials, the top-right status remains `ONLINE` while the side panel shows red `API AUTH`.

## Touch controls

- Tap an aircraft or callsign: select it and show details in the side panel.
- Tap empty radar space: clear the selection.
- Tap the right panel: cycle `Callsign → Details → Hidden`.
- Swipe left or right with an aircraft selected: cycle aircraft ordered by distance.
- Double-tap Range: toggle full/50% display radius.
- Long-press the radar area: open Quick Settings.
- Long-press the right panel: open System / Settings information.
- Tap an overlay to operate or close it.
- Swipe up or down while Help is open: scroll the instructions; taps and horizontal swipes in Help do not operate the radar.

### Quick Settings

Quickly toggle:

- Sweep line.
- Aircraft heading symbols.
- Callsign display.
- Ground aircraft; disabled by default.

### System / Settings information

Shows:

- Hostname and IP address.
- OpenSky API state and aircraft count.
- Radar-centre source and coordinates: `CENTER: CONFIG`, `CENTER: GPS WAIT`, or `CENTER: GPS`, plus latitude/longitude to six decimal places.
- CPU temperature.
- `PWR: OK`, a current power/thermal warning, or `PWR: HISTORY`.
- Web URL and access token.
- A QR code containing the complete Web URL and token for direct phone access.

`PWR: HISTORY` means undervoltage or throttling occurred earlier during this boot; it does not mean the condition is active now. Current undervoltage, overheating, or throttling is shown as an active warning.

### Help screen

Short-press Button 4 / GPIO 27 to open full-screen Help from the radar; press it again to return. Help covers:

- Tap, double-tap, long-press, and horizontal-swipe controls.
- How to open Quick Settings and System / Settings.
- GPIO assignments and short/long-press behavior for all four PiTFT buttons.
- The meaning of red priority flights, cyan selection rings, data age, STATUS, API, and Wi-Fi/Ethernet.
- The QR-code entry point for the Web configuration UI.

Thirteen lines are visible per page, with the current/total line range in the top-right corner. Swipe up for later content and down to go back. Help starts at the first line whenever it is opened.

## Physical buttons

- PiTFT Button 1 / GPIO 17: hold for 8 seconds to remove known Wi-Fi client profiles and start `PIcketRadar-Setup`.
- PiTFT Button 2 / GPIO 22: hold for 3 seconds to request a safe shutdown through `systemctl poweroff`.
- PiTFT Button 3 / GPIO 23: currently unused.
- PiTFT Button 4 / GPIO 27: short-press to toggle full-screen Help and the radar.

Install `systemd/50-picket-device-control.rules` to authorize AP creation, Wi-Fi control, and safe shutdown for the `rpi` service account.

The shutdown button deliberately requires a long press to prevent accidental operation. GPIO 22 uses an internal pull-up and is active low; after a continuous three-second press, the application runs `systemctl poweroff`. Do not change this to `loginctl poweroff`: the `loginctl` supplied by Raspberry Pi OS may not provide a `poweroff` command verb, producing `Unknown command verb 'poweroff'` in the journal.

GPIO 27 also uses an internal pull-up and is active low. Help toggles once when the button is released, with 50 ms debounce to prevent contact bounce from opening and closing it repeatedly.

## Web configuration

The Web UI listens on TCP port 8080 on all interfaces and is protected by a random access token. Open the URL or QR code shown on the System / Settings screen:

```text
http://<Pi-IP>:8080/?token=<access-token>
```

After authentication, the browser receives an HttpOnly, SameSite cookie. The service uses HTTP and should only be used on a trusted LAN or the device setup AP.

### Radar

- Latitude and Longitude: radar center; default is Taiwan Taoyuan International Airport at `25.080278, 121.232222`.
- Radius: API request and full display radius.
- Distance unit: km or NM.

### OpenSky OAuth2

- Client ID.
- Client Secret; leave blank to preserve the existing secret.
- Update interval: API polling period, minimum 10 seconds.

### Display

- Callsign, Altitude, and Speed.
- Radar scanline.
- Aircraft heading symbol.
- Highlighted flight 1–3: enter up to three OpenSky callsigns to watch; a blank field is disabled.
- Rotation: choose `90°` or `270°` from a drop-down; `270°` flips the current orientation by 180 degrees.
- Brightness: 10–100% in 5% steps through GPIO 18 PWM.

Priority-flight matching is an exact callsign match, but it ignores letter case and spaces; for example, `eva 123` matches `EVA123`. Duplicate entries are stored once. Each value may contain up to 12 ASCII letters, digits, `-`, or `_`. Leave all three fields blank to disable highlighting.

OpenSky reports the callsign broadcast by the aircraft transponder, which commonly uses an ICAO airline designator and may differ from the IATA flight number printed on a ticket. For example, an EVA Air flight may appear as `EVA123`, not `BR123`; use the callsign currently shown by the radar. When a match is within the displayed range, its aircraft symbol, heading marker, radar label, and selected name in the side panel are red.

Rotation affects both framebuffer output and capacitive-touch coordinates and must not be changed on only one side. If the rotation is unchanged, Save only restarts the radar. If it changes, the system:

1. Updates the PiTFT boot overlay through the restricted `picket-display-rotate@90/270.service`.
2. Backs up the current boot configuration as `config.txt.pvr-rotation-backup`.
3. Writes the same angle to `touch.rotation`.
4. Automatically reboots after responding to the Web request; reconnection normally takes about one minute.

If the boot-overlay update fails, the Web UI reports the error and does not save the new angle. If writing the configuration fails, the application attempts to restore the previous boot angle.

### USB GPS (NMEA 0183)

- Use external USB GPS for radar centre: enables or disables the dongle; disabled by default.
- Device path: `auto` tries `/dev/ttyUSB0` and then `/dev/ttyACM0`; a custom absolute path below `/dev/`, such as `/dev/serial/by-id/...`, is also accepted.
- Baud rate: 4800, 9600, 38400, or 115200; default 9600.

The GPS reader verifies NMEA checksums and accepts GGA or RMC sentences with a valid fix. When GPS is enabled:

1. While the dongle is absent or has no fix, the Radar latitude/longitude remain active; their defaults are Taoyuan Airport at `25.080278, 121.232222`.
2. After a valid fix, both the displayed radar centre and OpenSky bounding box move to the GPS coordinates.
3. If no new fix arrives for 15 seconds, the application falls back to the configured coordinates and returns to GPS after a new fix.
4. The information page shows yellow `GPS WAIT` or green `GPS` to identify the current source.

Prefer `/dev/serial/by-id/...` so adding another USB serial device does not change the tty number. The systemd service includes the `dialout` supplementary group. If the device cannot be opened, verify its path, baud rate, NMEA output, and `journalctl -u picket-virtual-radar`.

### Localization

- Altitude unit: m or ft.
- Speed unit: kt or km/h.
- Timezone, for example `Asia/Taipei`.

### Wi-Fi configuration

- Shows current client, AP, or Ethernet state.
- Lists scanned SSIDs, signal levels, and security modes.
- Select an SSID and enter its password.
- The client password is delivered through `nmcli --ask` stdin, never process arguments or logs.
- The current Web connection drops while changing networks; reconnect using the new IP.
- A failed client connection restores the setup AP automatically.

### Save and rollback

`Save and restart radar` interrupts the display and Web UI for roughly 3–5 seconds:

1. Validate the complete candidate configuration.
2. Back up the current file as `config.json.last-known-good`.
3. Commit atomically using a temporary file, `fsync`, and `os.replace`.
4. Let systemd restart the service.
5. Remove the pending marker after 15 seconds of healthy operation.
6. Restore last-known-good after three consecutive failed starts.

## Wi-Fi AP fallback

At normal boot the system first uses Wi-Fi profiles created by Raspberry Pi Imager or NetworkManager. If no network is usable:

1. Retry reconnection every 15 seconds.
2. Start a WPA2 setup AP after 45 seconds.
3. Show its SSID, password, `192.168.4.1`, Web URL, and token on screen.
4. Connect a phone and select a new Wi-Fi network in the Web UI.
5. Restore the AP if the client attempt fails.
6. After 15 minutes in AP mode, retry known networks and restore the AP again if needed.

Defaults:

```text
SSID: PIcketRadar-Setup
Password: picket-radar
Gateway: 192.168.4.1
Web: http://192.168.4.1:8080/
```

Ethernet is considered usable only when carrier, NetworkManager state, a valid IPv4 address, and an Ethernet default route are all present.

## OpenSky data and tracking

- Refreshes OAuth2 tokens before expiry without logging the Client Secret.
- Creates a latitude-aware bounding box from center and radius.
- Validates HTTP status, JSON schema, nulls, and unreasonable positions.
- Rejects missing coordinates, aircraft outside the configured radius, and ground aircraft by default.
- Default HTTP timeout: 8 seconds.
- Default polling interval: 15 seconds.
- Separate exponential backoff for rate-limit, authentication, and general failures.
- Keeps the last successful snapshot when the API fails; the application does not terminate.
- Uses ICAO24 as the unique identifier.
- Default interpolation period: 2 seconds.
- Maximum short-term prediction: 20 seconds.
- Removes aircraft after 90 seconds without data by default.

## Reliability and appliance operation

- Fixed 10 Hz logic and rendering capped at 30 FPS.
- RGB565 framebuffer output to `/dev/fb0`, with full-frame or dirty-rectangle mode.
- Clean SIGINT/SIGTERM shutdown of framebuffer, GPIO, touch, Web, and worker threads.
- 30-second systemd watchdog; hangs are terminated and restarted after 3 seconds.
- OpenSky and Wi-Fi operations have timeouts and do not block the display indefinitely.
- Temperature, current/historical undervoltage, and throttling monitoring.
- Journal limits: 50 MB persistent, 20 MB runtime, seven-day file rotation.
- Configuration mode `0600`, configuration directory mode `0700`.

The project currently does not use a read-only root filesystem because Web settings and last-known-good recovery require persistent writable configuration storage.

## Configuration file

Production configuration:

```text
/etc/picket-virtual-radar/config.json
```

Example: [config.example.json](config.example.json)

Sections: `display`, `runtime`, `radar`, `opensky`, `tracking`, `gps`, `touch`, `ui`, `localization`, `web`, and `wifi`. Priority flights are stored in `ui.highlight_callsigns` as a JSON array containing at most three strings.

Never commit a production file containing the OpenSky Client Secret, Web token, or Wi-Fi information.

## Installation

The installer preserves an existing `/etc/picket-virtual-radar/config.json`:

```sh
cd ~/picket-virtual-radar
sudo ./install.sh
```

Install device-control PolicyKit authorization:

```sh
sudo PVR_INSTALL_DEVICE_POLKIT=YES ./install.sh
```

The installer:

- Installs the application under `/opt/picket-virtual-radar`.
- Creates a virtual environment with access to Raspberry Pi OS system packages.
- Installs and enables the systemd service.
- Installs journald limits and baseline PolicyKit rules.
- Installs the restricted display-rotation helper and templated systemd service.
- Synchronizes an existing `pitft28-capacitive` overlay with the configured 90°/270° value and does not force it back to 90° during later reinstalls.

The device-control PolicyKit rule permits `rpi` to start only `picket-display-rotate@90.service` or `picket-display-rotate@270.service` and perform the required reboot. Arbitrary angles, other systemd units, and general root commands are not authorized.

### Updating an installed application

The service loads the installed package inside the virtual environment:

```text
/opt/picket-virtual-radar/.venv/lib/pythonX.Y/site-packages/picket_virtual_radar/
```

Editing only `/opt/picket-virtual-radar/src` therefore does not update the running application. Rerun the installer from the project directory so the source tree, virtual-environment package, systemd unit, and PolicyKit rules remain synchronized:

```sh
sudo PVR_INSTALL_DEVICE_POLKIT=YES ./install.sh
```

Confirm the module path actually loaded by the service environment with:

```sh
/opt/picket-virtual-radar/.venv/bin/python -c \
  'import picket_virtual_radar.system_health as m; print(m.__file__)'
```

## Maintenance commands

```sh
systemctl status picket-virtual-radar
journalctl -u picket-virtual-radar -f
sudo systemctl restart picket-virtual-radar
sudo systemctl stop picket-virtual-radar
```

Safe configuration summary without secrets:

```sh
/opt/picket-virtual-radar/.venv/bin/python \
  /opt/picket-virtual-radar/tools/report_safe_config.py
```

## Development and tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests cover configuration validation, projection, OpenSky, tracking, touch, transactional settings/rollback, backlight, Wi-Fi, and Range display zoom.

Non-destructive interrupted-write stress test:

```sh
/opt/picket-virtual-radar/.venv/bin/python \
  /opt/picket-virtual-radar/tools/test_config_power_loss.py
```

It uses a temporary directory on the same filesystem and does not modify production configuration.

## Troubleshooting

### Display or Web disappears after Save

```sh
systemctl status picket-virtual-radar
journalctl -u picket-virtual-radar -n 100 --no-pager
```

`Restart=always` should restore service in 3–5 seconds. Three consecutive failures restore last-known-good.

### `API AUTH`

Check Client ID and Client Secret. The application backs off and retries without exiting.

### `API ERROR`

Check `STATUS`, DNS, system time, and OpenSky availability. The last successful aircraft data remains temporarily available.

### `PWR: HISTORY`

Undervoltage or throttling occurred during this boot. Use a stable 5 V / 2.5 A or better power supply and a short, low-resistance cable.

### Brightness control is unavailable

Check the PiTFT GPIO 18 backlight jumper, `gpio` group, `lgpio`, and service log. The absence of `/sys/class/backlight` is normal for the capacitive model.

### GPIO 22 is detected but the Pi does not shut down

Inspect the complete journal for the current boot, not only application messages:

```sh
sudo journalctl -b --since "5 minutes ago" --no-pager
```

Check the following in order:

1. `physical safe shutdown requested on GPIO 22` means the button wiring, GPIO access, and long-press detection are working.
2. `loginctl: Unknown command verb 'poweroff'` must not appear. If it does, the service is still loading an old installed package; follow “Updating an installed application.”
3. If `safe shutdown command failed with exit code ...` appears, use the stderr on the same line to diagnose PolicyKit or systemd authorization.
4. Confirm that the rule exists and both services are active:

```sh
sudo test -f /etc/polkit-1/rules.d/50-picket-device-control.rules
sudo systemctl restart polkit.service
systemctl is-active polkit.service picket-virtual-radar.service
```

The rule's `subject.user` must match `User=` in `picket-virtual-radar.service`; both default to `rpi`. Passwordless `sudo` does not mean a systemd service can elevate directly because the unit uses `NoNewPrivileges=true`. Device operations should be authorized through the narrowly scoped PolicyKit rule.
