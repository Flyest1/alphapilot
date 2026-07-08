#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/alphapilot}"
SERVER_NAME="${2:-_}"
PYTHON_BIN="${PYTHON_BIN:-python3.10}"
SERVICE_USER="${SERVICE_USER:-alphapilot}"
ENV_DIR="/etc/alphapilot"
ENV_FILE="$ENV_DIR/backend.env"
ENV_CREATED=false

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/oracle/install_backend.sh /opt/alphapilot api.example.com"
  exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Repository not found at $APP_DIR. Clone alphapilot there first."
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN is required. Use an Ubuntu image that provides Python 3.10."
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
  cp "$APP_DIR/deploy/oracle/backend.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ENV_CREATED=true
  echo "Created $ENV_FILE. Edit it with real secrets before starting the service."
fi

cd "$APP_DIR/backend"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

cp "$APP_DIR/deploy/oracle/alphapilot-backend.service" /etc/systemd/system/alphapilot-backend.service
systemctl daemon-reload
if [ "$ENV_CREATED" = true ]; then
  systemctl enable alphapilot-backend
else
  systemctl enable --now alphapilot-backend
fi

if command -v nginx >/dev/null 2>&1; then
  sed "s|__SERVER_NAME__|$SERVER_NAME|g" \
    "$APP_DIR/deploy/oracle/nginx.conf.example" \
    > /etc/nginx/sites-available/alphapilot-backend
  ln -sfn /etc/nginx/sites-available/alphapilot-backend /etc/nginx/sites-enabled/alphapilot-backend
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl reload nginx
else
  echo "nginx is not installed. Install nginx or expose the service behind another HTTPS proxy."
fi

if systemctl is-active --quiet alphapilot-backend; then
  systemctl status alphapilot-backend --no-pager
else
  echo "alphapilot-backend is enabled but not started. Edit $ENV_FILE, then run:"
  echo "  sudo systemctl start alphapilot-backend"
fi
