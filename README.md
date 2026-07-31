# SkyPortal Home

Turn an original USB Skylanders Portal of Power into a physical smart-home controller. Place a figure on the portal and selected Govee, LIFX, or WLED lights take on its elemental color. Specific figures can override that color and activate Home Assistant scenes.

Designed for Raspberry Pi Zero 2 W and Raspberry Pi OS Bookworm (64-bit or 32-bit).

## What v1.0 supports

- Non-Xbox USB Portal of Power (`VID 1430`, `PID 0150`), including the
  Swap Force portal
- 684 character and retail-variant records from Spyro's Adventure through
  Imaginators, including SWAP Force halves, vehicles, items, and crystals
- Editable colors for Air, Earth, Fire, Life, Magic, Tech, Undead, and Water
- Current Govee Developer API discovery plus RGB, native white-temperature,
  and brightness control
- Local LIFX LAN discovery plus RGB, native white-temperature, and brightness
  control without a cloud key
- Local WLED discovery for ESP32/ESP8266 controllers, including RGB, RGBW/CCT,
  brightness, multi-segment output, and named presets
- Multiple selected Govee, LIFX, and WLED lights
- Per-character color overrides
- Per-character Home Assistant scene activation
- Per-element light profiles with individual colors, brightness, scenes, and
  music modes when supported by each Govee device
- Multi-figure element combinations with automatic even light splitting
- Searchable character and power-up palettes with current/recent recommendations
- Optional Home Assistant scenes on every palette, plus an empty-portal default
- Durable recent activity history
- Password-protected local setup UI on port `8099`
- Automatic startup and portal reconnection through systemd
- Local-only secret storage with `0600` permissions

Xbox 360 and Xbox One portals are not supported because they use Xbox-specific USB/authentication behavior. A Wii, Wii U, PS3, or PS4 USB portal is the safe choice.

## Hardware

1. Raspberry Pi Zero 2 W with Raspberry Pi OS and working Wi-Fi
2. A micro-USB OTG adapter or OTG hub
3. A non-Xbox USB Portal of Power
4. A power supply strong enough for the Pi and portal; a powered USB hub is recommended if the portal disconnects or flickers

## Install

```bash
git clone https://github.com/tmansmann0/skyportal-home.git
cd skyportal-home
chmod +x install.sh uninstall.sh
sudo ./install.sh
```

The installer prints the dashboard address and a unique setup token. Open `http://raspberrypi.local:8099` or the displayed IP address, enter that token, then:

1. Enter a Govee Developer API key.
2. Select **Discover devices**.
3. Check the lights that should react.
4. Adjust each light's color or white temperature and brightness.
5. Save and place a figure on the portal.

The API key is stored only in `/var/lib/skyportal-home/config.json` on the Pi and is never returned to the browser after saving.

LIFX bulbs can be added from **Settings → Discover LIFX bulbs** without a
cloud account or API key. The Pi and bulbs must be on the same LAN, and the
network must allow local UDP broadcast traffic. The app uses LIFX's official
product registry to match each bulb's RGB and supported white-temperature
range. Check the discovered bulbs, save settings, then customize them alongside
Govee lights in any palette.

WLED controllers can be added from **Settings → Discover WLED devices** using
their `_wled._tcp` mDNS advertisement. If multicast discovery is unavailable,
enter the controller's `.local` hostname or private IP address and choose
**Add by address**. The app reads the controller's segment capabilities and
named `/presets.json` entries, then offers compatible RGB, native white/CCT,
brightness, and preset controls in every palette.

## Home Assistant scenes

Create a [long-lived access token](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token), enter the Home Assistant URL and token, and add an override such as:

- Figure: Spyro
- Color: purple
- Scene: `scene.portal_spyro`

When Spyro is placed, the palette activates its selected output: the configured
lights or Home Assistant's `scene.turn_on` service.

## Operations

```bash
sudo systemctl status skyportal-home
sudo journalctl -u skyportal-home -f
sudo systemctl restart skyportal-home
```

Health endpoint: `http://raspberrypi.local:8099/health`

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
SKYPORTAL_CONFIG=./config.json python -m skyportal.app
```

The web UI works without a connected portal, which makes configuration and interface development possible on another computer.

## Figure database

The bundled offline database is a pinned snapshot of
[Skylandex](https://github.com/ssnofall/skylandex), which credits Texthead1's
Skylander IDs compilation. Its source revision and license are preserved in
`skyportal/data/`.

## Protocol notes and attribution

The portal protocol implementation is an independent Python implementation informed by the MIT-licensed [SkylandersToolkit](https://github.com/mandar1jn/SkylandersToolkit) project by Marijn Kneppers. Figure IDs are based on the community-maintained [Skylander IDs](https://github.com/Texthead1/Skylander-IDs) reference. Skylanders and related names are trademarks of their respective owners. This project is unofficial and is not affiliated with Activision, Govee, LIFX, or the WLED project.

## Security

- Do not expose port 8099 directly to the public internet.
- Rotate an API key if it has been pasted into chat, a terminal recording, or a public issue.
- Configuration is intentionally excluded from Git.
