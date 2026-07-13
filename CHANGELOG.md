# Changelog

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
