#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/yt-shorts"
SERVICE_NAME="yt-shorts"
APP_USER="ubuntu"
PYTHON_BIN="python3"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/oracle/install_service.sh"
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "${APP_DIR} not found. Copy the project there first."
  exit 1
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "${APP_DIR}/.env not found. Create it before installing service."
  exit 1
fi

cd "${APP_DIR}"

sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv .venv
sudo -u "${APP_USER}" bash -lc "source ${APP_DIR}/.venv/bin/activate && pip install --upgrade pip && pip install -r ${APP_DIR}/requirements.txt"

install -m 644 "${APP_DIR}/deploy/oracle/systemd/yt-shorts.service" "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"
sleep 2
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true

echo "Service installed. Logs: journalctl -u ${SERVICE_NAME} -f"
