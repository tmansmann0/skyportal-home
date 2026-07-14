# Changelog

## 1.4.0 — 2026-07-13

- Add an in-dialog preview action for every customizable palette
- Refresh Govee scene and DIY-scene compatibility once per new dashboard tab
  session, without periodic API polling
- Refresh scene compatibility immediately during Govee device discovery
- Route every palette through one mutually exclusive output mode: individual
  Govee controls, a Home Assistant scene, or DreamView
- Discover saved Scenic DreamView groups and activate one as a palette-wide
  alternative to individual light controls
- Refresh renamed DreamView groups during device discovery and fully hide
  individual light controls outside Govee mode
- Track the DreamView group activated by the controller and stop it only when
  transitioning away from or replacing that active DreamView

## 1.3.0 — 2026-07-12

- Treat SWAP Force tops and bottoms as two current characters by default, with
  mixed halves activating their corresponding advanced elemental combo
- Add Home Assistant actions to every customizable palette, with optional
  scene-only behavior
- Add a fully customizable No Skylander default palette
- Add durable portal and configuration activity history
- Recommend advanced combos from the figures currently on the portal
- Replace legacy figure overrides with searchable Figure Palettes and current
  or recently used recommendations
- Add equivalent Power Up Palettes for magic items and adventure pieces

## 1.2.0 — 2026-07-12

- Add per-element, per-light color and brightness profiles
- Add device-supported Govee scene and music-mode outputs
- Detect multiple figures and combine SWAP Force halves as one character
- Add advanced two-element profiles with automatic even light splitting
- Isolate individual Govee failures so one offline light does not block others
- Hide the save bar until configuration changes exist
- Keep stored API keys and Home Assistant tokens out of rendered dashboard HTML

## 1.1.0 — 2026-07-12

- Add a pinned 684-record, all-generation identification database
- Identify exact retail variants using the character and variant IDs
- Add Light, Dark, and safe fallback element colors
- Combine both SWAP Force tags into the full character name and element
- Read variant IDs from their correct bytes in figure block 1

## 1.0.1 — 2026-07-12

- Use HID `SET_REPORT` control transfers for Portal of Power commands, fixing
  Swap Force portals that stall interrupt/hidraw output writes on Linux
- Correct physical portal query indexes for slots 0 through 3
- Surface short USB writes instead of silently waiting for an impossible reply

## 1.0.0 — 2026-07-12

- Initial Raspberry Pi Zero 2 W release
- USB Portal of Power reader with automatic reconnect
- First-generation figure identification and element mapping
- Govee device discovery, RGB color, power, and brightness control
- Local setup dashboard with editable element palette
- Specific-figure color and Home Assistant scene overrides
- systemd service, udev permissions, installer, health endpoint, and tests
