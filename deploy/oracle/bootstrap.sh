#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/yt-shorts"
PYTHON_BIN="python3"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/oracle/bootstrap.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  git \
  ffmpeg \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  libpq-dev \
  ca-certificates

mkdir -p "${APP_DIR}"
chown -R ubuntu:ubuntu "${APP_DIR}" || true

echo "Bootstrap complete. Next steps:"
echo "1) Copy repo into ${APP_DIR}"
echo "2) Create ${APP_DIR}/.env"
echo "3) Run deploy/oracle/install_service.sh"
