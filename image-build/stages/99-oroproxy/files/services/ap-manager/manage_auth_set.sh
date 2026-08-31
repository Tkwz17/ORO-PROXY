#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 add|del <mac>" >&2
  exit 1
fi

action="$1"
mac="$2"

case "$action" in
  add)
    nft add element inet oroproxy authenticated_macs "{ $mac }"
    ;;
  del)
    nft delete element inet oroproxy authenticated_macs "{ $mac }" || true
    ;;
  *)
    echo "unknown action: $action" >&2
    exit 1
    ;;
esac
