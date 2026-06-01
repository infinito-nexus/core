#!/usr/bin/env bash
# Purge stale nixbld build users when their layout would block the
# multi-user Nix installer (descending UIDs as created by `useradd -r`
# on RHEL-family pkgmgr base images) and no live /nix/store exists.
#
# Idempotent. Safe to re-run.
#
# Three guards must all hold to purge:
#   1. No nix binary in known install paths.
#   2. nixbld2 UID < nixbld1 UID (the broken descending layout).
#   3. /nix/store does not exist (no live store to orphan).
set -euo pipefail

NIX_BINARY_CANDIDATES=(
  /nix/var/nix/profiles/default/bin/nix
  /nix/var/nix/profiles/per-user/root/profile/bin/nix
  /root/.nix-profile/bin/nix
  /usr/local/bin/nix
  /usr/bin/nix
)

found_binary=""
for p in "${NIX_BINARY_CANDIDATES[@]}"; do
  if [[ -x "$p" ]]; then
    found_binary="$p"
    break
  fi
done

if [[ -n "$found_binary" ]]; then
  echo "[UNCHANGED] nix binary present at ${found_binary}, leaving nixbld users intact"
  exit 0
fi

uid1="$(getent passwd nixbld1 | awk -F: '{print $3}')"
uid2="$(getent passwd nixbld2 | awk -F: '{print $3}')"

if [[ -z "$uid1" || -z "$uid2" ]]; then
  echo "[UNCHANGED] nixbld1/nixbld2 not both present, nothing to purge"
  exit 0
fi

if (( uid2 >= uid1 )); then
  echo "[UNCHANGED] nixbld UIDs ascending (nixbld1=${uid1}, nixbld2=${uid2}), no fix needed"
  exit 0
fi

if [[ -d /nix/store ]]; then
  echo "[FAIL] /nix/store exists but no nix binary found; refusing to purge build users" >&2
  exit 1
fi

removed=0
for i in $(seq 1 32); do
  if id "nixbld${i}" >/dev/null 2>&1; then
    userdel "nixbld${i}"
    removed=$((removed + 1))
  fi
done

if getent group nixbld >/dev/null; then
  groupdel nixbld
  removed=$((removed + 1))
fi

if (( removed > 0 )); then
  echo "[CHANGED] purged ${removed} stale nixbld entries (descending UID layout: nixbld1=${uid1}, nixbld2=${uid2})"
else
  echo "[UNCHANGED] no nixbld entries found"
fi
