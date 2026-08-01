#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
systemctl disable --now skyportal-home-update.timer 2>/dev/null || true
systemctl disable --now skyportal-home 2>/dev/null || true
rm -f /etc/systemd/system/skyportal-home.service \
  /etc/systemd/system/skyportal-home-update.service \
  /etc/systemd/system/skyportal-home-update.timer \
  /etc/udev/rules.d/60-skylanders-portal.rules \
  /usr/local/sbin/skyportal-home-update
rm -rf /opt/skyportal-home
rm -rf /opt/skyportal-home.previous /var/lib/skyportal-home/updater
systemctl daemon-reload
echo "Application removed. Configuration remains in /var/lib/skyportal-home."
