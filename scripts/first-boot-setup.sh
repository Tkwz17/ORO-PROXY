#!/usr/bin/env bash
set -euo pipefail

SETUP_DIR="/etc/oroproxy"
BOOT_COPY="${OROPROXY_BOOT_COPY:-/boot/firmware/oroproxy-setup-code.txt}"
[[ -d "$(dirname "$BOOT_COPY")" ]] || BOOT_COPY="/boot/oroproxy-setup-code.txt"
TLS_DIR="$SETUP_DIR/tls"

mkdir -p "$SETUP_DIR" "$TLS_DIR"

if [[ ! -f "$SETUP_DIR/setup_code" ]]; then
  setup_code="$(openssl rand -hex 4)"
  echo "$setup_code" > "$SETUP_DIR/setup_code"
  chmod 600 "$SETUP_DIR/setup_code"
  {
    echo "OroProxy first-run setup code: $setup_code"
    echo "After Wi-Fi setup, open https://oroproxy.local:8443 and accept the device certificate before entering this code."
  } | tee "$BOOT_COPY"
  chmod 644 "$BOOT_COPY"
fi

if [[ ! -f "$SETUP_DIR/session_secret" ]]; then
  openssl rand -hex 32 > "$SETUP_DIR/session_secret"
  chmod 600 "$SETUP_DIR/session_secret"
fi

if [[ ! -f "$TLS_DIR/server.key" || ! -f "$TLS_DIR/server.crt" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -subj "/CN=oroproxy.local" \
    -addext "subjectAltName=DNS:oroproxy.local" \
    -keyout "$TLS_DIR/server.key" \
    -out "$TLS_DIR/server.crt"
  chmod 600 "$TLS_DIR/server.key"
  chmod 644 "$TLS_DIR/server.crt"
fi

systemctl daemon-reload
systemctl enable --now \
  oroproxy-ap-manager.service \
  oroproxy-quota-daemon.service \
  oroproxy-portal-api.service \
  oroproxy-proxy.service \
  oroproxy-portal-web.service \
  oroproxy-update-check.timer
