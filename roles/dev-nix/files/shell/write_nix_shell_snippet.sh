#!/usr/bin/env bash
set -euo pipefail

dest="${1:-}"

if [[ -z "$dest" ]]; then
  echo "[FAIL] Usage: $0 <destination_path>" >&2
  exit 2
fi

tmp="$(mktemp)"
cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

cat >"$tmp" <<'EOF'
if [ -e /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]; then
  . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi
EOF

if [[ -f "$dest" ]] && cmp -s "$tmp" "$dest"; then
  echo "[UNCHANGED] nix shell snippet already up to date: $dest"
  exit 0
fi

install -D -m 0644 "$tmp" "$dest"
echo "[CHANGED] wrote nix shell snippet: $dest"
