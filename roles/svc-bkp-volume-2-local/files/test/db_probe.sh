#!/usr/bin/env bash
set -euo pipefail

: "${BKP_TEST_DATABASES_CSV:?}"

MODE="${1:?usage: db_probe.sh seed TOKEN | verify PRE_TOKEN POST_TOKEN MANIFEST}"
PROBE_TABLE="infinito_backup_restore_probe"

validate_token() {
	if [[ ! "${1}" =~ ^[A-Za-z0-9_-]+$ ]]; then
		echo "FAIL: unsafe database probe token"
		exit 1
	fi
}

engine_for_container() {
	local image
	image="$(container inspect -f '{{.Config.Image}}' "${1}")"
	case "${image}" in
	*postgres* | *postgis*) printf 'postgres\n' ;;
	*mariadb* | *mysql*) printf 'mariadb\n' ;;
	*) return 1 ;;
	esac
}

container_for_instance() {
	local candidate engine instance="${1}"
	mapfile -t candidates < <(container ps --filter "volume=${instance}_data" --format '{{.Names}}')
	if ((${#candidates[@]} < 1)); then
		mapfile -t candidates < <(container ps --filter "name=${instance}" --format '{{.Names}}')
	fi
	for candidate in "${candidates[@]}"; do
		if engine="$(engine_for_container "${candidate}")"; then
			printf '%s;%s\n' "${candidate}" "${engine}"
			return 0
		fi
	done
	return 1
}

container_for_volume() {
	local candidate engine volume="${1}" expected_engine="${2}"
	while IFS= read -r candidate; do
		[[ -n "${candidate}" ]] || continue
		if engine="$(engine_for_container "${candidate}")" && [[ "${engine}" == "${expected_engine}" ]]; then
			printf '%s\n' "${candidate}"
			return 0
		fi
	done < <(container ps --filter "volume=${volume}" --format '{{.Names}}')
	return 1
}

run_seed() {
	local container database engine instance password resolved token="${1}" user
	local seeded=0
	validate_token "${token}"
	if [[ ! -f "${BKP_TEST_DATABASES_CSV}" ]]; then
		echo "FAIL: databases csv missing at ${BKP_TEST_DATABASES_CSV}"
		exit 1
	fi

	while IFS=';' read -r instance database user password; do
		[[ -n "${instance}" ]] || continue
		[[ "${database}" != "*" ]] || continue
		if ! resolved="$(container_for_instance "${instance}")"; then
			echo "SKIP: no running database container found for instance '${instance}'"
			continue
		fi
		IFS=';' read -r container engine <<<"${resolved}"
		case "${engine}" in
		postgres)
			container exec -e "PGPASSWORD=${password}" "${container}" \
				psql -X -v ON_ERROR_STOP=1 -U "${user}" -d "${database}" -c \
				"CREATE TABLE IF NOT EXISTS ${PROBE_TABLE} (token text PRIMARY KEY); INSERT INTO ${PROBE_TABLE} (token) VALUES ('${token}') ON CONFLICT (token) DO NOTHING;" >/dev/null
			;;
		mariadb)
			container exec -e "MYSQL_PWD=${password}" "${container}" \
				mariadb --batch --skip-column-names -u "${user}" "${database}" -e \
				"CREATE TABLE IF NOT EXISTS ${PROBE_TABLE} (token varchar(128) PRIMARY KEY); INSERT IGNORE INTO ${PROBE_TABLE} (token) VALUES ('${token}');" >/dev/null
			;;
		esac
		echo "OK: seeded database restore probe in ${database} (${engine})"
		seeded=$((seeded + 1))
	done < <(tail -n +2 "${BKP_TEST_DATABASES_CSV}")
	echo "OK: seeded ${seeded} database restore probe(s)"
}

probe_count() {
	local container="${1}" database="${2}" engine="${3}" password="${4}" token="${5}" user="${6}"
	case "${engine}" in
	postgres)
		container exec -e "PGPASSWORD=${password}" "${container}" \
			psql -X -Atq -v ON_ERROR_STOP=1 -U "${user}" -d "${database}" -c \
			"SELECT COUNT(*) FROM ${PROBE_TABLE} WHERE token = '${token}';" | tr -d '[:space:]'
		;;
	mariadb)
		container exec -e "MYSQL_PWD=${password}" "${container}" \
			mariadb --batch --skip-column-names -u "${user}" "${database}" -e \
			"SELECT COUNT(*) FROM ${PROBE_TABLE} WHERE token = '${token}';" | tr -d '[:space:]'
		;;
	*)
		echo "FAIL: unsupported database engine '${engine}'"
		exit 1
		;;
	esac
}

run_verify() {
	local container database engine manifest="${3}" password post_count pre_count
	local pre_token="${1}" post_token="${2}" row user verified=0 volume
	validate_token "${pre_token}"
	validate_token "${post_token}"
	if [[ ! -s "${manifest}" ]]; then
		echo "FAIL: restored database manifest missing or empty at ${manifest}"
		exit 1
	fi

	while IFS=';' read -r engine volume database; do
		[[ -n "${engine}" && -n "${volume}" && -n "${database}" ]] || continue
		row="$(awk -F';' -v db="${database}" 'NR > 1 && $2 == db { print; exit }' "${BKP_TEST_DATABASES_CSV}")"
		if [[ -z "${row}" ]]; then
			echo "FAIL: no databases.csv row for restored database '${database}'"
			exit 1
		fi
		IFS=';' read -r _instance _database user password <<<"${row}"
		if ! container="$(container_for_volume "${volume}" "${engine}")"; then
			echo "FAIL: no running ${engine} container mounts restored volume ${volume}"
			exit 1
		fi
		pre_count="$(probe_count "${container}" "${database}" "${engine}" "${password}" "${pre_token}" "${user}")"
		post_count="$(probe_count "${container}" "${database}" "${engine}" "${password}" "${post_token}" "${user}")"
		if [[ "${pre_count}" != "1" ]] || [[ "${post_count}" != "0" ]]; then
			echo "FAIL: ${database} restore probe mismatch (pre=${pre_count}, post=${post_count})"
			exit 1
		fi
		echo "OK: ${database} contains the pre-backup probe and excludes the post-backup probe"
		verified=$((verified + 1))
	done <"${manifest}"
	echo "OK: verified ${verified} destructively restored database(s)"
}

case "${MODE}" in
seed)
	run_seed "${2:?seed token required}"
	;;
verify)
	run_verify "${2:?pre token required}" "${3:?post token required}" "${4:?manifest required}"
	;;
*)
	echo "FAIL: unsupported db_probe mode '${MODE}'"
	exit 1
	;;
esac
