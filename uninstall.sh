#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
systemctl disable --now skyportal-home 2>/dev/null || true
rm -f /etc/systemd/system/skyportal-home.service /etc/udev/rules.d/60-skylanders-portal.rules
rm -rf /opt/skyportal-home
systemctl daemon-reload
echo "Application removed. Configuration remains in /var/lib/skyportal-home."
