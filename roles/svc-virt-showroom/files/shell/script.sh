#!/bin/bash
set -euo pipefail

bridge="$1"

if ! iptables -n -L DOCKER-USER >/dev/null 2>&1; then
  exit 0
fi

allow() {
  if ! iptables -C DOCKER-USER "$@" 2>/dev/null; then
    iptables -I DOCKER-USER "$@"
  fi
}

allow -o "${bridge}" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
allow -i "${bridge}" -j ACCEPT
