#!/bin/sh
# Param: ENGINE      postgres | mariadb | redis | openldap
# Param: RUN_ID      unique id of this run; keys and rows are scoped to it
# Param: DURATION_S  seconds to keep writing before the audit dump; SIGUSR1 ends the writes early
# Param: INTERVAL_S  pause between two writes
# Param: TIMEOUT_S   ceiling of one connection + write
# Param: SECRET_FILE shell env file with HOST, PORT, USER, PASSWORD and DATABASE or BASE_DN
set -u

: "${ENGINE:?}" "${RUN_ID:?}" "${DURATION_S:?}" "${INTERVAL_S:?}" "${TIMEOUT_S:?}" "${SECRET_FILE:?}"
# shellcheck source=/dev/null
. "${SECRET_FILE}"

WRITER_USER="${USER}"
# shellcheck disable=SC2153  # PASSWORD comes from the sourced SECRET_FILE
PGPASSWORD="${PASSWORD}"
MYSQL_PWD="${PASSWORD}"
REDISCLI_AUTH="${PASSWORD}"
export PGPASSWORD MYSQL_PWD REDISCLI_AUTH
LDAP_PASSWORD_FILE="$(mktemp)"
chmod 600 "${LDAP_PASSWORD_FILE}"
printf '%s' "${PASSWORD}" >"${LDAP_PASSWORD_FILE}"

uptime_ms() {
	read -r up _ </proc/uptime
	frac="${up#*.}"
	frac="${frac#0}"
	echo "$((${up%.*} * 1000 + frac * 10))"
}

NS_CLOCK=false
ns="$(date +%s%N)"
case "${ns}" in
*[!0-9]*) ;;
*) [ "${#ns}" -ge 19 ] && NS_CLOCK=true ;;
esac
if [ "${NS_CLOCK}" = false ]; then
	second="$(date +%s)"
	while [ "$(date +%s)" = "${second}" ]; do :; done
	EPOCH_OFFSET_MS=$(((second + 1) * 1000 - $(uptime_ms)))
fi

now_ms() {
	if [ "${NS_CLOCK}" = true ]; then
		ns="$(date +%s%N)"
		echo "${ns%??????}"
	else
		echo "$(($(uptime_ms) + EPOCH_OFFSET_MS))"
	fi
}

prepare() {
	case "${ENGINE}" in
	postgres)
		psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DATABASE}" -qAt \
			-c "CREATE TABLE IF NOT EXISTS failover_check (run text NOT NULL, seq bigint NOT NULL, PRIMARY KEY (run, seq))"
		;;
	mariadb)
		printf '%s\n' "CREATE DATABASE IF NOT EXISTS ${DATABASE}; CREATE TABLE IF NOT EXISTS ${DATABASE}.failover_check (run VARCHAR(64) NOT NULL, seq BIGINT NOT NULL, PRIMARY KEY (run, seq)); CREATE USER IF NOT EXISTS 'failover_checker'@'%' IDENTIFIED BY '${PASSWORD}'; GRANT INSERT, SELECT ON ${DATABASE}.* TO 'failover_checker'@'%'" |
			mariadb -h "${HOST}" -P "${PORT}" -u "${USER}" &&
			WRITER_USER=failover_checker
		;;
	redis) ;;
	openldap)
		printf 'dn: ou=failover-check,%s\nobjectClass: organizationalUnit\nou: failover-check\n' "${BASE_DN}" |
			ldapadd -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" -c >/dev/null 2>&1
		ldapsearch -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
			-LLL -s base -b "ou=failover-check,${BASE_DN}" dn >/dev/null
		;;
	*)
		echo "unknown ENGINE ${ENGINE}" >&2
		exit 2
		;;
	esac
}

write_one() {
	case "${ENGINE}" in
	postgres)
		PGCONNECT_TIMEOUT="${TIMEOUT_S}" timeout "${TIMEOUT_S}" \
			psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DATABASE}" -qAt \
			-c "INSERT INTO failover_check (run, seq) VALUES ('${RUN_ID}', $1)"
		;;
	mariadb)
		timeout "${TIMEOUT_S}" mariadb --connect-timeout="${TIMEOUT_S}" -h "${HOST}" -P "${PORT}" \
			-u "${WRITER_USER}" "${DATABASE}" \
			-e "INSERT INTO failover_check (run, seq) VALUES ('${RUN_ID}', $1)"
		;;
	redis)
		[ "$(timeout "${TIMEOUT_S}" redis-cli -h "${HOST}" -p "${PORT}" SET "failover:${RUN_ID}:$1" 1)" = "OK" ]
		;;
	openldap)
		printf 'dn: cn=%s-%s,ou=failover-check,%s\nobjectClass: device\ncn: %s-%s\n' \
			"${RUN_ID}" "$1" "${BASE_DN}" "${RUN_ID}" "$1" |
			timeout "${TIMEOUT_S}" ldapadd -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
				-o nettimeout="${TIMEOUT_S}"
		;;
	esac
}

DUMP_TIMEOUT_S=30
DUMP_FILE="$(mktemp)"

dump_present() {
	case "${ENGINE}" in
	postgres)
		PGCONNECT_TIMEOUT="${DUMP_TIMEOUT_S}" timeout "${DUMP_TIMEOUT_S}" \
			psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DATABASE}" -qAt \
			-c "SELECT seq FROM failover_check WHERE run = '${RUN_ID}'"
		;;
	mariadb)
		timeout "${DUMP_TIMEOUT_S}" mariadb --connect-timeout="${DUMP_TIMEOUT_S}" \
			-h "${HOST}" -P "${PORT}" -u "${USER}" "${DATABASE}" -N -B \
			-e "SELECT seq FROM failover_check WHERE run = '${RUN_ID}'"
		;;
	redis)
		timeout "${DUMP_TIMEOUT_S}" redis-cli -h "${HOST}" -p "${PORT}" \
			--scan --pattern "failover:${RUN_ID}:*" >"${DUMP_FILE}" &&
			sed 's/.*://' "${DUMP_FILE}"
		;;
	openldap)
		timeout "${DUMP_TIMEOUT_S}" ldapsearch -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
			-o nettimeout="${DUMP_TIMEOUT_S}" -LLL -b "ou=failover-check,${BASE_DN}" "(cn=${RUN_ID}-*)" cn >"${DUMP_FILE}" &&
			sed -n "s/^cn: ${RUN_ID}-//p" "${DUMP_FILE}"
		;;
	esac
}

until prepare; do
	sleep 1
done

echo "start ${RUN_ID} $(now_ms)"
deadline=$(($(date +%s) + DURATION_S))
trap 'deadline=0' USR1
seq=0
while [ "$(date +%s)" -lt "${deadline}" ]; do
	seq=$((seq + 1))
	if write_one "${seq}" >/dev/null 2>&1; then
		echo "ack ${seq} $(now_ms)"
	else
		echo "fail ${seq} $(now_ms)"
	fi
	sleep "${INTERVAL_S}"
done

until present="$(dump_present)"; do
	sleep 1
done
printf '%s\n' "${present}" | sed -n 's/^\([0-9][0-9]*\)$/present \1/p'
echo "done"
exec sleep infinity
