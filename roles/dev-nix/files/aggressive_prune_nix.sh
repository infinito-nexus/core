#!/usr/bin/env bash
# Aggressively prune Nix data: GC + optimise. CI/Debug cleanup to prevent
# huge disk usage from Nix store + old generations.
#
# Args:
#   $1 nix_bin -- absolute path to the nix binary
set -euo pipefail

nix_bin="${1:?nix binary path required}"
nix_bin_dir="$(dirname "$nix_bin")"
nix_collect="$nix_bin_dir/nix-collect-garbage"
nix_store="$nix_bin_dir/nix-store"

# Remove old generations for all users + root (aggressive)
if [ -x "$nix_collect" ]; then
  gc_rc=0
  gc_out="$("$nix_collect" -d 2>&1)" || gc_rc=$?
  printf '%s\n' "$gc_out"
  if [ "$gc_rc" -ne 0 ] && ! printf '%s' "$gc_out" | grep -q 'cannot unlink .*Directory not empty'; then
    exit "$gc_rc"
  fi
else
  "$nix_bin" store gc || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

# Additional GC pass (useful on some setups / older nix)
if [ -x "$nix_store" ]; then
  "$nix_store" --gc || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
else
  "$nix_bin" store gc || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

# Deduplicate store paths to reduce disk usage (can take a bit).
# Prefer modern CLI; fall back to nix-store on older setups.
if ! "$nix_bin" store optimise; then
  if [ -x "$nix_store" ]; then
    "$nix_store" --optimise || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
fi
