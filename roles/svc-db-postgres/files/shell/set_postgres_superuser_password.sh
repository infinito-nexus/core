#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   set_postgres_superuser_password.sh <container_name> <new_password> <role>
#
# The role is the cluster's superuser: "postgres" for the shared engine, and
# whatever POSTGRES_USER a dedicated one was initialised with. Both are reached
# the same way, over the container's local socket, which authenticates by peer
# and therefore needs no password -- that is what lets a rotated credential be
# written into an engine nobody can log into any more.

container_raw="${1:-}"
new_pw="${2:-}"
role="${3:-}"

if [[ -z "$container_raw" || -z "$new_pw" || -z "$role" ]]; then
  echo "Usage: $0 <container_name> <new_password> <role>" >&2
  exit 2
fi

container=""
eval "container=$container_raw"

pg_exec() {
  container exec -e PG_ROLE="$role" "$container" bash -lc \
    "psql -U \"\$PG_ROLE\" -d postgres -Atc '$1'" 2>/dev/null
}

# Retry TCP auth up to 15 times (30s) to handle HBA reload delay
auth_test() {
  for _ in {1..15}; do
    # shellcheck disable=SC2016
    if container exec -e PGPASSWORD="$new_pw" -e PG_ROLE="$role" "$container" bash -lc \
        'psql -h 127.0.0.1 -p 5432 -U "$PG_ROLE" -d postgres -Atc "SELECT 1" >/dev/null 2>&1'; then
      return 0
    fi
    sleep 2
  done
  return 1
}

result=""

for _ in {1..30}; do
  hba_file=""
  for _ in {1..30}; do
    if hba_file=$(pg_exec 'SHOW hba_file;'); then
      break
    fi
    sleep 2
  done
  if [[ -z "$hba_file" ]]; then
    sleep 2; continue
  fi

  backup="${hba_file}.bak_ansible_pwcheck_$$"

  if ! container exec "$container" bash -lc "cp -a \"$hba_file\" \"$backup\"" 2>/dev/null; then
    sleep 2; continue
  fi

  cleanup() {
    container exec "$container" bash -lc "if [ -f \"$backup\" ]; then cp -a \"$backup\" \"$hba_file\" && rm -f \"$backup\"; fi" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
    pg_exec 'SELECT pg_reload_conf();' >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  }
  trap 'cleanup' EXIT

  if ! container exec "$container" bash -lc "{
    echo 'host all all 127.0.0.1/32 scram-sha-256'
    cat \"$backup\"
  } > \"$hba_file\"" 2>/dev/null; then
    cleanup; sleep 2; continue
  fi

  if ! pg_exec 'SELECT pg_reload_conf();' >/dev/null; then
    cleanup; sleep 2; continue
  fi

  pre_ok=0
  if auth_test; then pre_ok=1; fi

  # shellcheck disable=SC2016
  if ! container exec -e NEW_POSTGRES_PASSWORD="$new_pw" -e PG_ROLE="$role" "$container" bash -lc '
    psql -U "$PG_ROLE" -d postgres -v ON_ERROR_STOP=1 -v role="$PG_ROLE" -v password="$NEW_POSTGRES_PASSWORD" <<'"'"'SQL'"'"'
ALTER USER :"role" WITH PASSWORD :'"'"'password'"'"';
SQL
' 2>/dev/null; then
    cleanup; sleep 2; continue
  fi

  post_ok=0
  if auth_test; then post_ok=1; fi

  cleanup

  if [[ "$pre_ok" -eq 0 && "$post_ok" -eq 1 ]]; then
    result="[CHANGED] New password did not work before, and works now."
  elif [[ "$pre_ok" -eq 1 && "$post_ok" -eq 1 ]]; then
    result="[UNCHANGED] New password already worked before."
  fi
  break
done

if [[ -z "$result" ]]; then
  echo "[FAIL] Password auth test failed even after ALTER USER." >&2
  exit 1
fi

echo "$result"
