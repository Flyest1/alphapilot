#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/alphapilot}"
PYTHON_BIN="${PYTHON_BIN:-python3.10}"
SERVICE_USER="${SERVICE_USER:-alphapilot}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/oracle/deploy_backend.sh /opt/alphapilot"
  exit 1
fi

cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR" >/dev/null 2>&1 || true
git fetch origin
git checkout main
git pull --ff-only origin main

cd "$APP_DIR/backend"
if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
systemctl daemon-reload
systemctl restart alphapilot-backend

curl -fsS --max-time 30 http://127.0.0.1:8000/health
echo
systemctl status alphapilot-backend --no-pager
