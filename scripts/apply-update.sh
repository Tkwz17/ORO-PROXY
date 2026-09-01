#!/usr/bin/env bash
set -euo pipefail

REPO="Tkwz17/ORO-PROXY"
INSTALL_ROOT="/opt/oroproxy"
STATE_DIR="/var/lib/oroproxy"
VERSION_FILE="$INSTALL_ROOT/VERSION"
UPDATE_CHECK_SCRIPT="$INSTALL_ROOT/scripts/update-check.sh"

mkdir -p "$STATE_DIR"
current="0.0.0"
[[ -f "$VERSION_FILE" ]] && current="$(cat "$VERSION_FILE")"

latest_tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name",""))')"
if [[ -z "$latest_tag" ]]; then
  echo "failed to fetch latest release tag" >&2
  exit 1
fi

needs_update="$(python3 - "$current" "$latest_tag" <<'PY'
import sys
from packaging.version import Version
current, latest = sys.argv[1], sys.argv[2]
print("yes" if Version(latest.lstrip("v")) > Version(current.lstrip("v")) else "no")
PY
)"

if [[ "$needs_update" != "yes" ]]; then
  echo "already up to date ($current)"
  [[ -x "$UPDATE_CHECK_SCRIPT" ]] && "$UPDATE_CHECK_SCRIPT" || true
  exit 0
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
archive="$tmpdir/oroproxy.tar.gz"

curl -fsSL "https://github.com/${REPO}/archive/refs/tags/${latest_tag}.tar.gz" -o "$archive"
tar -xzf "$archive" -C "$tmpdir"
src_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d -name 'ORO-PROXY-*' | head -n1)"

if [[ -z "$src_dir" ]]; then
  echo "failed to unpack update payload" >&2
  exit 1
fi

install -d "$INSTALL_ROOT"
cp -a "$src_dir/services" "$INSTALL_ROOT/"
cp -a "$src_dir/systemd" "$INSTALL_ROOT/"
cp -a "$src_dir/scripts" "$INSTALL_ROOT/"

chmod +x "$INSTALL_ROOT/scripts"/*.sh
chmod +x "$INSTALL_ROOT/services/ap-manager/manage_auth_set.sh"

(cd "$INSTALL_ROOT/services/proxy" && go build -o proxy .)
(cd "$INSTALL_ROOT/services/quota-daemon" && go build -o quota-daemon .)
pip3 install --break-system-packages -r "$INSTALL_ROOT/services/portal-api/requirements.txt"

install -m 0644 "$INSTALL_ROOT/systemd"/*.service /etc/systemd/system/
install -m 0644 "$INSTALL_ROOT/systemd"/*.timer /etc/systemd/system/

echo "${latest_tag#v}" > "$VERSION_FILE"

systemctl daemon-reload
systemctl restart \
  oroproxy-ap-manager.service \
  oroproxy-quota-daemon.service \
  oroproxy-portal-api.service \
  oroproxy-proxy.service \
  oroproxy-portal-web.service

[[ -x "$UPDATE_CHECK_SCRIPT" ]] && "$UPDATE_CHECK_SCRIPT" || true

echo "updated to ${latest_tag}"
