#!/usr/bin/env bash
set -euo pipefail

REPO="Tkwz17/ORO-PROXY"
STATE_DIR="/var/lib/oroproxy"
CURRENT_VERSION_FILE="/opt/oroproxy/VERSION"
STATUS_FILE="$STATE_DIR/update-status.json"

mkdir -p "$STATE_DIR"
current="0.0.0"
[[ -f "$CURRENT_VERSION_FILE" ]] && current="$(cat "$CURRENT_VERSION_FILE")"

latest_tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name",""))')"
if [[ -z "$latest_tag" ]]; then
  echo '{"error":"unable to fetch latest release"}' > "$STATUS_FILE"
  exit 0
fi

python3 - "$current" "$latest_tag" "$STATUS_FILE" <<'PY'
import json, sys
from packaging.version import Version
current, latest, out = sys.argv[1:4]
data = {
  "current": current,
  "latest": latest,
  "update_available": Version(latest.lstrip("v")) > Version(current.lstrip("v")),
}
open(out, "w", encoding="utf-8").write(json.dumps(data))
PY
