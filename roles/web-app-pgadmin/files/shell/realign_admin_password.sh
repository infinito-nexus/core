#!/bin/sh
# Usage:
#   Piped into the `sh -s` of the running pgAdmin container, no arguments.
#
#   PGADMIN_ADMIN_EMAIL     login of the internal account to realign
#   PGADMIN_ADMIN_PASSWORD  password it must accept afterwards
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
set -eu

marker="/var/lib/pgadmin/.admin_password_sha256"

if [ -z "${PGADMIN_ADMIN_EMAIL:-}" ] || [ -z "${PGADMIN_ADMIN_PASSWORD:-}" ]; then
  echo "[FAIL] PGADMIN_ADMIN_EMAIL or PGADMIN_ADMIN_PASSWORD is empty." >&2
  exit 1
fi

declared_sha="$(printf '%s' "$PGADMIN_ADMIN_PASSWORD" | sha256sum | cut -d' ' -f1)"
current_sha=""
if [ -f "$marker" ]; then
  current_sha="$(cat "$marker")"
fi

if [ "$current_sha" = "$declared_sha" ]; then
  echo "[UNCHANGED] the pgAdmin administrator already accepts the declared password"
  exit 0
fi

if ! out="$(/venv/bin/python3 /pgadmin4/setup.py update-user \
  "$PGADMIN_ADMIN_EMAIL" --admin --password "$PGADMIN_ADMIN_PASSWORD" 2>&1)"; then
  echo "[FAIL] setup.py update-user exited non-zero: ${out}" >&2
  exit 1
fi

case "$out" in
*"User Details"*) ;;
*)
  echo "[FAIL] setup.py update-user did not realign the account: ${out}" >&2
  exit 1
  ;;
esac

if ! printf '%s' "$declared_sha" >"$marker"; then
  echo "[FAIL] the password was realigned but the marker stayed unwritten." >&2
  exit 1
fi

echo "[CHANGED] the pgAdmin administrator was realigned with the declared password"
