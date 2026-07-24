#!/usr/bin/env bash
#
# Postgres-specific rescue diagnostics: capture pg_hba.conf into the shared
# rescue diagnostics folder so it ships in the uploaded snapshot next to the
# generic capture. pg_hba.conf is the auth config the generic rescue script
# cannot capture, which is exactly what a failed TCP-auth wait needs. Prints
# one summary line and always exits 0 so the rescue flow continues to the fail task.
#
# Required environment:
#   POSTGRES_CONTAINER_ADDRESS   exec address of the postgres container
#   PGPASSWORD                   postgres superuser password
set -u

: "${POSTGRES_CONTAINER_ADDRESS:?POSTGRES_CONTAINER_ADDRESS not set}"
: "${PGPASSWORD:?PGPASSWORD not set}"
export PGPASSWORD

OUT_BASE="${INFINITO_RESCUE_DIAGNOSTICS_DIR:?INFINITO_RESCUE_DIAGNOSTICS_DIR not set (SPOT: group_vars/all/05_paths.yml)}"
mkdir -p "${OUT_BASE}"
out="${OUT_BASE}/postgres-pg_hba.txt"

runtime() {
	if command -v container >/dev/null 2>&1; then
		container "$@"
	else
		docker "$@"
	fi
}

{
	hba="$(runtime exec --env "PGPASSWORD=${PGPASSWORD}" "${POSTGRES_CONTAINER_ADDRESS}" \
		psql -U postgres -d postgres -Atc 'SHOW hba_file;' 2>/dev/null || true)"
	if [ -n "${hba}" ]; then
		echo "hba_file=${hba}"
		runtime exec "${POSTGRES_CONTAINER_ADDRESS}" sh -lc \
			"sed -n '1,200p' \"${hba}\" 2>/dev/null || true"
	else
		echo "hba_file could not be determined"
	fi
} >"${out}" 2>&1 || true

echo "🩺 Postgres pg_hba.conf captured to ${out}"
exit 0
