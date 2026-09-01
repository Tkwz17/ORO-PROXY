#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-boot}"
WLAN_IFACE="${OROPROXY_WLAN_IFACE:-wlan0}"
AP_ASSETS_DIR="/opt/oroproxy/services/ap-manager"
WIFI_CONFIG_FILE="${OROPROXY_WIFI_CONFIG_FILE:-/etc/oroproxy/home_wifi.json}"
NETWORK_STATE_FILE="${OROPROXY_NETWORK_STATE_FILE:-/var/lib/oroproxy/network-state.json}"
WPA_CONF="${OROPROXY_WPA_CONF:-/etc/wpa_supplicant/wpa_supplicant-oroproxy.conf}"
WPA_PID_FILE="${OROPROXY_WPA_PID_FILE:-/run/wpa_supplicant-oroproxy.pid}"

write_state() {
  local mode="$1"
  local ssid="${2:-}"
  local error="${3:-}"
  mkdir -p "$(dirname "$NETWORK_STATE_FILE")"
  python3 - "$NETWORK_STATE_FILE" "$mode" "$ssid" "$error" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "mode": sys.argv[2],
    "connected_ssid": sys.argv[3] or None,
    "last_error": sys.argv[4] or None,
}
target.write_text(json.dumps(payload), encoding="utf-8")
target.chmod(0o600)
PY
}

read_wifi_value() {
  local key="$1"
  python3 - "$WIFI_CONFIG_FILE" "$key" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = data.get(sys.argv[2], "")
print(value if isinstance(value, str) else "")
PY
}

enable_ap_assets() {
  cp "$AP_ASSETS_DIR/hostapd.conf" /etc/hostapd/hostapd.conf
  cp "$AP_ASSETS_DIR/dnsmasq.conf" /etc/dnsmasq.d/oroproxy.conf
  cp "$AP_ASSETS_DIR/avahi-oroproxy.service" /etc/avahi/services/oroproxy.service
  nft -f "$AP_ASSETS_DIR/nftables.conf"
}

stop_custom_wpa() {
  if [[ -f "$WPA_PID_FILE" ]]; then
    kill "$(cat "$WPA_PID_FILE")" 2>/dev/null || true
    rm -f "$WPA_PID_FILE"
  fi
}

start_ap_mode() {
  local error_message="${1:-}"
  stop_custom_wpa
  ip link set "$WLAN_IFACE" up || true
  enable_ap_assets
  systemctl restart hostapd dnsmasq avahi-daemon
  write_state "ap" "" "$error_message"
}

connect_home_network() {
  if [[ ! -f "$WIFI_CONFIG_FILE" ]]; then
    start_ap_mode "wifi credentials missing"
    return 1
  fi

  local ssid
  local wifi_key
  ssid="$(read_wifi_value ssid)"
  wifi_key="$(read_wifi_value psk)"
  if [[ -z "$ssid" || -z "$wifi_key" ]]; then
    start_ap_mode "wifi credentials invalid"
    return 1
  fi

  write_state "connecting" "$ssid" ""
  systemctl stop hostapd dnsmasq || true
  stop_custom_wpa
  ip link set "$WLAN_IFACE" down || true
  ip link set "$WLAN_IFACE" up || true
  wpa_passphrase "$ssid" "$wifi_key" > "$WPA_CONF"
  chmod 600 "$WPA_CONF"
  wpa_supplicant -B -i "$WLAN_IFACE" -c "$WPA_CONF" -P "$WPA_PID_FILE"

  if command -v dhcpcd >/dev/null 2>&1; then
    dhcpcd -n "$WLAN_IFACE" || true
  elif command -v dhclient >/dev/null 2>&1; then
    dhclient -1 "$WLAN_IFACE" || true
  fi

  for _ in $(seq 1 25); do
    if [[ "$(iwgetid "$WLAN_IFACE" --raw 2>/dev/null || true)" == "$ssid" ]] && ip -4 -o addr show "$WLAN_IFACE" | grep -q " inet "; then
      write_state "home" "$ssid" ""
      return 0
    fi
    sleep 1
  done

  start_ap_mode "failed to join ${ssid}"
  return 1
}

case "$ACTION" in
  boot)
    if [[ -f "$WIFI_CONFIG_FILE" ]]; then
      connect_home_network || true
    else
      start_ap_mode ""
    fi
    ;;
  connect)
    connect_home_network
    ;;
  ap)
    start_ap_mode ""
    ;;
  *)
    echo "usage: $0 [boot|connect|ap]" >&2
    exit 1
    ;;
esac
