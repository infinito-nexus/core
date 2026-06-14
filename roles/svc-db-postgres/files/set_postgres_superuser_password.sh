#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   tmp.sh <container_name> <new_postgres_password>

container_raw="${1:-}"
new_pw="${2:-}"

if [[ -z "$container_raw" || -z "$new_pw" ]]; then
  echo "Usage: $0 <container_name> <new_postgres_password>" >&2
  exit 2
fi

# In swarm mode the lookup emits `"$(/usr/bin/resolve-container-id <svc> <stack>)"`.
# `eval` makes bash re-evaluate the subshell so we get the live task id; in
# compose mode the arg is a bare name and `eval` is a noop.
container=""
eval "container=$container_raw"

pg_exec() {
  container exec "$container" bash -lc "psql -U postgres -d postgres -Atc '$1'" 2>/dev/null
}

# Retry TCP auth up to 15 times (30s) to handle HBA reload delay
auth_test() {
  for _ in {1..15}; do
    if container exec -e PGPASSWORD="$new_pw" "$container" bash -lc \
        'psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -Atc "SELECT 1" >/dev/null 2>&1'; then
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
    container exec "$container" bash -lc "if [ -f \"$backup\" ]; then cp -a \"$backup\" \"$hba_file\" && rm -f \"$backup\"; fi" >/dev/null 2>&1 || true
    pg_exec 'SELECT pg_reload_conf();' >/dev/null 2>&1 || true
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
  if ! container exec -e NEW_POSTGRES_PASSWORD="$new_pw" "$container" bash -lc '
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -v password="$NEW_POSTGRES_PASSWORD" <<'"'"'SQL'"'"'
ALTER USER postgres WITH PASSWORD :'"'"'password'"'"';
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

backup="${hba_file}.bak_ansible_pwcheck_$$"

# Backup hba
container exec "$container" bash -lc "cp -a \"$hba_file\" \"$backup\""

# shellcheck disable=SC2329,SC2317
restore_hba() {
  # Restore on exit (best effort)
  container exec "$container" bash -lc "if [ -f \"$backup\" ]; then cp -a \"$backup\" \"$hba_file\" && rm -f \"$backup\"; fi" >/dev/null 2>&1 || true
  container exec "$container" bash -lc "psql -U postgres -d postgres -Atc 'SELECT pg_reload_conf();' >/dev/null 2>&1" || true
}

# Register direct function trap so ShellCheck sees the invocation path.
trap restore_hba EXIT

# Force password auth for local TCP (127.0.0.1)
# Prepend a strict rule so it matches first.
container exec "$container" bash -lc "{
  echo 'host all all 127.0.0.1/32 scram-sha-256'
  cat \"$backup\"
} > \"$hba_file\""

# Reload config
container exec "$container" bash -lc "psql -U postgres -d postgres -Atc 'SELECT pg_reload_conf();' >/dev/null"

# Helper: test password auth explicitly over TCP
auth_test() {
  container exec -e PGPASSWORD="$new_pw" "$container" bash -lc \
    'psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -Atc "SELECT 1" >/dev/null 2>&1'
}

pre_ok=0
if auth_test; then
  pre_ok=1
fi

# Set password (socket, no auth dependency)
# shellcheck disable=SC2016
container exec -e NEW_POSTGRES_PASSWORD="$new_pw" "$container" bash -lc '
  psql -U postgres -d postgres -v ON_ERROR_STOP=1 -v password="$NEW_POSTGRES_PASSWORD" <<'"'"'SQL'"'"'
ALTER USER postgres WITH PASSWORD :'"'"'password'"'"';
SQL
'

post_ok=0
if auth_test; then
  post_ok=1
fi

if [[ "$pre_ok" -eq 0 && "$post_ok" -eq 1 ]]; then
  echo "[CHANGED] New password did not work before, and works now."
  exit 0
fi

if [[ "$pre_ok" -eq 1 && "$post_ok" -eq 1 ]]; then
  echo "[UNCHANGED] New password already worked before."
  exit 0
fi

echo "[FAIL] Password auth test failed even after ALTER USER." >&2
exit 1
