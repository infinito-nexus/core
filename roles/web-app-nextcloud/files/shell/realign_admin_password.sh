#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   realign_admin_password.sh <container> <run_as_user> <admin_username> <occ_path>
#   OC_PASS: the declared password, read from the environment only.
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.

container="${1:-}"
run_as="${2:-}"
admin_user="${3:-}"
occ="${4:-}"

if [[ -z "$container" || -z "$run_as" || -z "$admin_user" || -z "$occ" ]]; then
  echo "Usage: $0 <container> <run_as_user> <admin_username> <occ_path>" >&2
  exit 2
fi

if [[ -z "${OC_PASS:-}" ]]; then
  echo "[FAIL] OC_PASS is empty; refusing to set an empty administrator password." >&2
  exit 1
fi

marker="/var/www/html/config/.admin_password_sha256"
declared_sha="$(printf '%s' "$OC_PASS" | sha256sum | cut -d' ' -f1)"

current_sha="$(container exec -u "$run_as" "$container" \
  sh -c "cat '$marker' 2>/dev/null || true")"

if [[ "$current_sha" == "$declared_sha" ]]; then
  echo "[UNCHANGED] Administrator password already matches the declared one."
  exit 0
fi

if ! container exec -u "$run_as" -e "OC_PASS=$OC_PASS" "$container" \
  php "$occ" user:resetpassword --password-from-env "$admin_user" >/dev/null; then
  echo "[FAIL] occ user:resetpassword failed for '$admin_user'." >&2
  exit 1
fi

if ! container exec -u "$run_as" -e "SHA=$declared_sha" "$container" \
  sh -c "printf '%s' \"\$SHA\" > '$marker'"; then
  echo "[FAIL] Password was reset but the marker could not be written." >&2
  exit 1
fi

echo "[CHANGED] Administrator password did not match the declared one, and does now."
