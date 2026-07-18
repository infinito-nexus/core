#!/usr/bin/env bash
# DB purge for stacks (best effort):
# - Tries BOTH backends: Postgres + MariaDB
# - Detects DB name best effort from /opt/compose/<STACK>/.env/env (Keycloak style vars),
#   otherwise falls back to DB name = <STACK>.
#
# Usage:
#   ./purge/entity/db.sh [--wipe-data-only] <STACK1> [STACK2] [...]
#
# Flags:
#   --wipe-data-only  Truncate all tables (keep schema) instead of dropping the DB

set -euo pipefail

WIPE_DATA_ONLY=false

while [[ "${1:-}" == --* ]]; do
	case "${1}" in
	--wipe-data-only)
		WIPE_DATA_ONLY=true
		shift
		;;
	--help | -h)
		cat <<'EOF'
Usage:
  purge/entity/db.sh [--wipe-data-only] <STACK1> [STACK2] [...]

Flags:
  --wipe-data-only  Truncate all tables (keep schema) instead of dropping DB
EOF
		exit 0
		;;
	*)
		echo "ERROR: Unknown flag: ${1}" >&2
		exit 2
		;;
	esac
done

if [[ "$#" -lt 1 ]]; then
	echo "ERROR: No stack names provided." >&2
	exit 2
fi

log() { echo ">>> $*"; }
warn() { echo "!!! WARNING: $*" >&2; }

env_get() {
	local env_file="$1"
	local key="$2"

	awk -F= -v k="$key" '
    $1 ~ "^[[:space:]]*"k"[[:space:]]*$" {
      v=$0
      sub("^[^=]*=","",v)
      gsub(/^[[:space:]]+|[[:space:]]+$/,"",v)
      if (v ~ /^".*"$/) { sub(/^"/,"",v); sub(/"$/,"",v) }
      print v
      exit
    }
  ' "${env_file}"
}

run_no_stdin() { "$@" </dev/null; }

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

drop_postgres_db_best_effort() {
	local db_name="$1"

	if ! container ps --format '{{.Names}}' | grep -qx 'postgres'; then
		warn "Postgres container 'postgres' not running — skipping Postgres DROP for '${db_name}'"
		return 0
	fi

	local admin_db="postgres"
	[[ "${db_name}" == "postgres" ]] && admin_db="template1"

	log "Dropping Postgres database '${db_name}' (admin db: ${admin_db})..."

	set +e
	docker exec -i postgres psql -U postgres -d "${admin_db}" <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${db_name}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${db_name}";
SQL
	local rc=$?
	set -e

	[[ $rc -ne 0 ]] && warn "Postgres DROP DATABASE failed for '${db_name}' (rc=${rc})"
}

truncate_postgres_db_best_effort() {
	local db_name="$1"

	if ! container ps --format '{{.Names}}' | grep -qx 'postgres'; then
		warn "Postgres container 'postgres' not running — skipping Postgres TRUNCATE for '${db_name}'"
		return 0
	fi

	log "Truncating all tables in Postgres database '${db_name}'..."

	set +e
	docker exec -i postgres psql -U postgres -d "${db_name}" <<'SQL'
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
  LOOP
    EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' CASCADE';
  END LOOP;
END $$;
SQL
	local rc=$?
	set -e

	[[ $rc -ne 0 ]] && warn "Postgres TRUNCATE failed for '${db_name}' (rc=${rc})"
}

# ---------------------------------------------------------------------------
# MariaDB
# ---------------------------------------------------------------------------

drop_mariadb_db_best_effort() {
	local db_name="$1"

	if ! container ps --format '{{.Names}}' | grep -qx 'mariadb'; then
		warn "MariaDB container 'mariadb' not running — skipping MariaDB DROP for '${db_name}'"
		return 0
	fi

	case "${db_name}" in
	mysql | information_schema | performance_schema | sys)
		warn "Refusing to drop MariaDB system database '${db_name}'"
		return 0
		;;
	esac

	local mariadb_env="/opt/compose/mariadb/.env/env"
	[[ ! -f "${mariadb_env}" ]] && {
		warn "MariaDB env file not found (${mariadb_env}) — skipping MariaDB DROP"
		return 0
	}

	local root_pw
	root_pw="$(env_get "${mariadb_env}" MARIADB_ROOT_PASSWORD || true)"
	[[ -z "${root_pw}" ]] && {
		warn "MARIADB_ROOT_PASSWORD not found — skipping MariaDB DROP"
		return 0
	}

	log "Dropping MariaDB database '${db_name}'..."

	set +e
	run_no_stdin docker exec mariadb mariadb -uroot -p"${root_pw}" \
		-e "DROP DATABASE IF EXISTS \`${db_name}\`;"
	local rc=$?
	set -e

	[[ $rc -ne 0 ]] && warn "MariaDB DROP DATABASE failed for '${db_name}' (rc=${rc})"
}

truncate_mariadb_db_best_effort() {
	local db_name="$1"

	if ! container ps --format '{{.Names}}' | grep -qx 'mariadb'; then
		warn "MariaDB container 'mariadb' not running — skipping MariaDB TRUNCATE for '${db_name}'"
		return 0
	fi

	local mariadb_env="/opt/compose/mariadb/.env/env"
	[[ ! -f "${mariadb_env}" ]] && {
		warn "MariaDB env file not found (${mariadb_env}) — skipping MariaDB TRUNCATE"
		return 0
	}

	local root_pw
	root_pw="$(env_get "${mariadb_env}" MARIADB_ROOT_PASSWORD || true)"
	[[ -z "${root_pw}" ]] && {
		warn "MARIADB_ROOT_PASSWORD not found — skipping MariaDB TRUNCATE"
		return 0
	}

	log "Truncating all tables in MariaDB database '${db_name}'..."

	set +e
	truncates="$(
		run_no_stdin docker exec mariadb mariadb -uroot -p"${root_pw}" -N -B "${db_name}" -e "
      SELECT CONCAT('TRUNCATE TABLE \`', table_name, '\`;')
      FROM information_schema.tables
      WHERE table_schema = DATABASE();
    "
	)"
	local gen_rc=$?
	if [[ $gen_rc -ne 0 ]]; then
		set -e
		warn "MariaDB TRUNCATE statement generation failed for '${db_name}' (rc=${gen_rc})"
		return 0
	fi

	{
		echo "SET FOREIGN_KEY_CHECKS=0;"
		echo "${truncates}"
		echo "SET FOREIGN_KEY_CHECKS=1;"
	} | run_no_stdin docker exec -i mariadb mariadb -uroot -p"${root_pw}" "${db_name}"
	local rc=$?
	set -e

	[[ $rc -ne 0 ]] && warn "MariaDB TRUNCATE failed for '${db_name}' (rc=${rc})"
}

purge_db_both_backends_best_effort() {
	local db_name="$1"

	if [[ "${WIPE_DATA_ONLY}" == "true" ]]; then
		truncate_postgres_db_best_effort "${db_name}"
		truncate_mariadb_db_best_effort "${db_name}"
	else
		drop_postgres_db_best_effort "${db_name}"
		drop_mariadb_db_best_effort "${db_name}"
	fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

overall_rc=0

for STACK_NAME in "$@"; do
	(
		set -euo pipefail

		STACK_DIR="/opt/compose/${STACK_NAME}"
		ENV_FILE="${STACK_DIR}/.env/env"

		DB_NAME="${STACK_NAME}"
		DB_BACKEND="" # informational only

		if [[ -f "${ENV_FILE}" ]]; then
			KC_DB="$(env_get "${ENV_FILE}" KC_DB || true)"
			KC_DB_URL="$(env_get "${ENV_FILE}" KC_DB_URL || true)"

			if [[ -n "${KC_DB}" ]]; then
				echo "${KC_DB}" | grep -qi postgres && DB_BACKEND="postgres" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
				echo "${KC_DB}" | grep -qi mariadb && DB_BACKEND="mariadb" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
			fi

			if [[ -n "${KC_DB_URL}" ]]; then
				echo "${KC_DB_URL}" | grep -qi postgresql && DB_BACKEND="postgres" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
				echo "${KC_DB_URL}" | grep -qi mariadb && DB_BACKEND="mariadb" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
				DB_NAME="$(echo "${KC_DB_URL}" | sed -E 's|.*/([^/?#]+).*|\1|')"
			fi

			if [[ -z "${DB_BACKEND}" ]]; then
				grep -qi postgres "${ENV_FILE}" && DB_BACKEND="postgres" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
			fi
			if [[ -z "${DB_BACKEND}" ]]; then
				grep -qi mariadb "${ENV_FILE}" && DB_BACKEND="mariadb" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
			fi
		else
			warn "Env file not found (${ENV_FILE}) — DB name defaults to stack name '${DB_NAME}'"
		fi

		if [[ -n "${DB_BACKEND}" ]]; then
			log "DB purge (informational backend=${DB_BACKEND}) | stack=${STACK_NAME} | db=${DB_NAME}"
		else
			log "DB purge (backend unknown; trying BOTH) | stack=${STACK_NAME} | db=${DB_NAME}"
		fi

		purge_db_both_backends_best_effort "${DB_NAME}"
	) || {
		rc=$?
		overall_rc=1
		warn "DB purge failed for '${STACK_NAME}' (rc=${rc}) — continuing"
	}
done

exit "${overall_rc}"
