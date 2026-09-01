#!/usr/bin/env bash
# Switch wlan0 between the temporary OROAP setup network and the configured home Wi-Fi.
set -euo pipefail

ACTION="${1:-boot}"
WLAN_IFACE="${OROPROXY_WLAN_IFACE:-wlan0}"
AP_ASSETS_DIR="${OROPROXY_AP_ASSETS_DIR:-/opt/oroproxy/services/ap-manager}"
WIFI_CONFIG_FILE="${OROPROXY_WIFI_CONFIG_FILE:-/etc/oroproxy/home_wifi.json}"
NETWORK_STATE_FILE="${OROPROXY_NETWORK_STATE_FILE:-/var/lib/oroproxy/network-state.json}"
WPA_CONF="${OROPROXY_WPA_CONF:-/etc/wpa_supplicant/wpa_supplicant-oroproxy.conf}"
WPA_PID_FILE="${OROPROXY_WPA_PID_FILE:-/run/wpa_supplicant-oroproxy.pid}"
CONNECT_TIMEOUT="${OROPROXY_CONNECT_TIMEOUT:-30}"

write_state() {
  local mode="$1" ssid="${2:-}" error="${3:-}"
  mkdir -p "$(dirname "$NETWORK_STATE_FILE")"
  python3 - "$NETWORK_STATE_FILE" "$mode" "$ssid" "$error" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
p.write_text(json.dumps({"mode": sys.argv[2], "connected_ssid": sys.argv[3] or None, "last_error": sys.argv[4] or None}), encoding="utf-8")
p.chmod(0o600)
PY
}

read_wifi_value() {
  python3 - "$WIFI_CONFIG_FILE" "$1" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get(sys.argv[2], "")
print(value if isinstance(value, str) else "")
PY
}

install_ap_assets() {
  install -D -m 0644 "$AP_ASSETS_DIR/hostapd.conf" /etc/hostapd/hostapd.conf
  install -D -m 0644 "$AP_ASSETS_DIR/dnsmasq.conf" /etc/dnsmasq.d/oroproxy.conf
  install -D -m 0644 "$AP_ASSETS_DIR/avahi-oroproxy.service" /etc/avahi/services/oroproxy.service
}

clear_ap_firewall() {
  nft delete table inet oroproxy 2>/dev/null || true
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
  install_ap_assets
  clear_ap_firewall
  ip link set "$WLAN_IFACE" up || true
  nft -f "$AP_ASSETS_DIR/nftables.conf"
  systemctl restart avahi-daemon
  systemctl restart hostapd dnsmasq
  write_state "ap" "" "$error_message"
}

write_wpa_config() {
  local ssid="$1" wifi_key="$2"
  mkdir -p "$(dirname "$WPA_CONF")"
  if [[ -n "$wifi_key" ]]; then
    wpa_passphrase "$ssid" "$wifi_key" > "$WPA_CONF"
  else
    python3 - "$WPA_CONF" "$ssid" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text("ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev\nnetwork={\n    ssid=" + json.dumps(sys.argv[2]) + "\n    key_mgmt=NONE\n}\n", encoding="utf-8")
PY
  fi
  chmod 600 "$WPA_CONF"
}

connect_home_network() {
  if [[ ! -f "$WIFI_CONFIG_FILE" ]]; then
    start_ap_mode "Wi-Fi credentials are missing"
    return 1
  fi

  local ssid wifi_key
  ssid="$(read_wifi_value ssid)"
  wifi_key="$(read_wifi_value psk)"
  if [[ -z "$ssid" ]]; then
    start_ap_mode "Wi-Fi SSID is missing"
    return 1
  fi

  write_state "connecting" "$ssid" ""
  install_ap_assets
  # Stop every AP-only component before wlan0 becomes a station.  In particular,
  # remove the NAT table so home-network traffic is never captive-portal redirected.
  systemctl stop hostapd dnsmasq || true
  clear_ap_firewall
  stop_custom_wpa
  ip addr flush dev "$WLAN_IFACE" || true
  ip link set "$WLAN_IFACE" down || true
  ip link set "$WLAN_IFACE" up || true
  write_wpa_config "$ssid" "$wifi_key"
  wpa_supplicant -B -i "$WLAN_IFACE" -c "$WPA_CONF" -P "$WPA_PID_FILE"

  if command -v dhcpcd >/dev/null 2>&1; then
    dhcpcd -n "$WLAN_IFACE" || true
  elif command -v dhclient >/dev/null 2>&1; then
    dhclient -1 "$WLAN_IFACE" || true
  fi

  for _ in $(seq 1 "$CONNECT_TIMEOUT"); do
    if [[ "$(iwgetid "$WLAN_IFACE" --raw 2>/dev/null || true)" == "$ssid" ]] && ip -4 -o addr show "$WLAN_IFACE" | grep -q ' inet '; then
      # Avahi is intentionally kept active: it advertises oroproxy.local on the
      # home LAN after the setup AP is shut down.
      systemctl restart avahi-daemon
      write_state "home" "$ssid" ""
      return 0
    fi
    sleep 1
  done

  start_ap_mode "Could not join ${ssid}; check the SSID and password."
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
  connect) connect_home_network ;;
  ap) start_ap_mode "" ;;
  *) echo "usage: $0 [boot|connect|ap]" >&2; exit 1 ;;
esac
