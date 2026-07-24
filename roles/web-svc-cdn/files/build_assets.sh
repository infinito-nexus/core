#!/usr/bin/env sh
# Mirror every deployed role's frontend dependencies into the CDN web root
# under jsdelivr's own path scheme, so a served asset URL differs from the
# public one only by host: <root>/npm/<pkg>@<version>/<file>.
#
# Env:
#   CDN_WEB_ROOT   directory served at https://cdn.<domain>/ (required)
#   ROLES_DIR      directory holding <app>/package.json + package-lock.json (required)
set -eu

: "${CDN_WEB_ROOT:?}"
: "${ROLES_DIR:?}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

for lock in "${ROLES_DIR}"/*/package-lock.json; do
  [ -f "$lock" ] || continue
  src="$(dirname "$lock")"
  dir="$work/$(basename "$src")"
  mkdir -p "$dir"
  cp "$src/package.json" "$lock" "$dir/"
  ( cd "$dir" && npm ci --no-audit --no-fund --ignore-scripts )
  find "$dir/node_modules" -name package.json -maxdepth 3 -path "*/node_modules/*" | while read -r pkgjson; do
    pdir="$(dirname "$pkgjson")"
    name="$(node -p "require('$pkgjson').name || ''")"
    ver="$(node -p "require('$pkgjson').version || ''")"
    if [ -z "$name" ] || [ -z "$ver" ]; then continue; fi
    dest="${CDN_WEB_ROOT}/npm/${name}@${ver}"
    [ -d "$dest" ] && continue
    mkdir -p "$dest"
    cp -R "$pdir"/. "$dest"/
  done
done
