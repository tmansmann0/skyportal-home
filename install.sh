#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo: sudo ./install.sh"
  exit 1
fi

APP_DIR=/opt/skyportal-home
DATA_DIR=/var/lib/skyportal-home
SERVICE_USER=skyportal

apt-get update
apt-get install -y python3 python3-venv python3-dev libhidapi-hidraw0 libhidapi-dev build-essential

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
  groupadd --system "$SERVICE_USER"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_USER" --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$DATA_DIR"
cp -R skyportal requirements.txt pyproject.toml "$APP_DIR"/
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# Persist the initial setup token before the service starts. ConfigStore keeps
# defaults in memory until save() is called, while the installer reads the token
# from disk below.
if [[ ! -f "$DATA_DIR/config.json" ]]; then
  (
    cd "$APP_DIR"
    sudo -u "$SERVICE_USER" env SKYPORTAL_CONFIG="$DATA_DIR/config.json" \
      "$APP_DIR/.venv/bin/python" -c \
      'from skyportal.config import ConfigStore; store = ConfigStore(); store.save()'
  )
fi

install -m 0644 deploy/60-skylanders-portal.rules /etc/udev/rules.d/60-skylanders-portal.rules
install -m 0644 deploy/skyportal-home.service /etc/systemd/system/skyportal-home.service
udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
systemctl enable --now skyportal-home

sleep 2
TOKEN=$(python3 -c 'import json; print(json.load(open("/var/lib/skyportal-home/config.json"))["setup_token"])')
IP=$(hostname -I | awk '{print $1}')
echo
echo "SkyPortal Home is installed."
echo "Open: http://${IP:-raspberrypi.local}:8099"
echo "Setup token: $TOKEN"
echo
echo "Save this token. The config file is readable only by the service account."
