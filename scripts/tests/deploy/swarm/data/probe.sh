#!/bin/sh
# Param: ENGINE      postgres | mariadb | redis | openldap
# Param: MODE        ddl | marker-write | marker-read | idle | memberof-seed
# Param: ARG         marker token (marker-*), idle seconds (idle)
# Param: SECRET_FILE shell env file with HOST, PORT, USER, PASSWORD and DATABASE or BASE_DN
# Output: "probe <key> <value>" records, then "probe-done"
set -u

: "${ENGINE:?}" "${MODE:?}" "${SECRET_FILE:?}"
ARG="${ARG:-}"
# shellcheck source=/dev/null
. "${SECRET_FILE}"

# shellcheck disable=SC2153  # PASSWORD comes from the sourced SECRET_FILE
PGPASSWORD="${PASSWORD}"
MYSQL_PWD="${PASSWORD}"
REDISCLI_AUTH="${PASSWORD}"
export PGPASSWORD MYSQL_PWD REDISCLI_AUTH
LDAP_ERROR_FILE="$(mktemp)"
LDAP_PASSWORD_FILE="$(mktemp)"
chmod 600 "${LDAP_PASSWORD_FILE}"
printf '%s' "${PASSWORD}" >"${LDAP_PASSWORD_FILE}"

record() {
	echo "probe $1 $2"
}

sql() {
	case "${ENGINE}" in
	postgres)
		psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DATABASE}" -X -qAt -v ON_ERROR_STOP=1 -c "$1"
		;;
	mariadb)
		mariadb -h "${HOST}" -P "${PORT}" -u "${USER}" -N -B "${DATABASE}" -e "$1"
		;;
	esac
}

ldap_add() {
	ldapadd -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" -c
}

ddl() {
	table="failover_ddl_$(date +%s)"
	if sql "CREATE TABLE ${table} (id INT PRIMARY KEY, note VARCHAR(32))" &&
		sql "INSERT INTO ${table} (id, note) VALUES (1, 'a'), (2, 'b')" &&
		sql "UPDATE ${table} SET note = 'c' WHERE id = 2" &&
		sql "ALTER TABLE ${table} ADD COLUMN extra INT" &&
		sql "CREATE INDEX ${table}_note ON ${table} (note)" &&
		[ "$(sql "SELECT note FROM ${table} WHERE id = 2")" = "c" ] &&
		sql "DELETE FROM ${table} WHERE id = 1" &&
		[ "$(sql "SELECT COUNT(*) FROM ${table}")" = "1" ] &&
		sql "DROP TABLE ${table}"; then
		record ddl ok
	else
		record ddl fail
	fi
}

marker_write() {
	case "${ENGINE}" in
	postgres | mariadb)
		if [ "${ENGINE}" = mariadb ]; then
			mariadb -h "${HOST}" -P "${PORT}" -u "${USER}" -e "CREATE DATABASE IF NOT EXISTS ${DATABASE}" 2>"${LDAP_ERROR_FILE}" || return 1
		fi
		sql "CREATE TABLE IF NOT EXISTS failover_marker (token VARCHAR(64) PRIMARY KEY)" 2>"${LDAP_ERROR_FILE}" &&
			sql "INSERT INTO failover_marker (token) VALUES ('${ARG}')" 2>>"${LDAP_ERROR_FILE}"
		;;
	redis)
		[ "$(redis-cli -h "${HOST}" -p "${PORT}" SET "failover:marker:${ARG}" 1)" = "OK" ]
		;;
	openldap)
		printf 'dn: ou=failover-check,%s\nobjectClass: organizationalUnit\nou: failover-check\n\ndn: cn=marker-%s,ou=failover-check,%s\nobjectClass: device\ncn: marker-%s\n' \
			"${BASE_DN}" "${ARG}" "${BASE_DN}" "${ARG}" | ldap_add >/dev/null 2>"${LDAP_ERROR_FILE}"
		ldapsearch -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
			-LLL -s base -b "cn=marker-${ARG},ou=failover-check,${BASE_DN}" dn >/dev/null 2>>"${LDAP_ERROR_FILE}"
		;;
	esac
}

marker_read() {
	case "${ENGINE}" in
	postgres | mariadb)
		[ "$(sql "SELECT token FROM failover_marker WHERE token = '${ARG}'")" = "${ARG}" ]
		;;
	redis)
		[ "$(redis-cli -h "${HOST}" -p "${PORT}" GET "failover:marker:${ARG}")" = "1" ]
		;;
	openldap)
		ldapsearch -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
			-LLL -s base -b "cn=marker-${ARG},ou=failover-check,${BASE_DN}" dn | grep -q '^dn:'
		;;
	esac
}

idle() {
	case "${ENGINE}" in
	postgres)
		out="$({
			echo "SELECT 'first';"
			sleep "${ARG}"
			echo "SELECT 'second';"
		} |
			psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DATABASE}" -X -qAt 2>&1)"
		;;
	mariadb)
		out="$({
			echo "SELECT 'first';"
			sleep "${ARG}"
			echo "SELECT 'second';"
		} |
			mariadb -h "${HOST}" -P "${PORT}" -u "${USER}" -N -B "${DATABASE}" 2>&1)"
		;;
	redis)
		out="$({
			echo "ECHO first"
			sleep "${ARG}"
			echo "ECHO second"
		} |
			redis-cli -h "${HOST}" -p "${PORT}" 2>&1)"
		;;
	openldap)
		out="$(
			python3 - "${HOST}" "${PORT}" "${ARG}" <<'PY'
import socket, sys, time
bind = bytes.fromhex("300c020101600702010304008000")
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=10) as conn:
    conn.sendall(bind)
    print("first" if conn.recv(64)[5:6] == b"\x61" else "no-bind")
    time.sleep(float(sys.argv[3]))
    conn.sendall(bind.replace(b"\x02\x01\x01", b"\x02\x01\x02", 1))
    print("second" if conn.recv(64)[5:6] == b"\x61" else "dropped")
PY
		)"
		;;
	esac
	if printf '%s\n' "${out}" | grep -q 'second'; then
		record idle ok
	else
		record idle fail
		record idle-detail "$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-200)"
	fi
}

memberof_seed() {
	printf 'dn: ou=failover-check,%s\nobjectClass: organizationalUnit\nou: failover-check\n\ndn: cn=failover-member,ou=failover-check,%s\nobjectClass: device\ncn: failover-member\n\ndn: cn=failover-group,ou=failover-check,%s\nobjectClass: groupOfNames\ncn: failover-group\nmember: cn=failover-member,ou=failover-check,%s\n' \
		"${BASE_DN}" "${BASE_DN}" "${BASE_DN}" "${BASE_DN}" | ldap_add >/dev/null 2>"${LDAP_ERROR_FILE}"
	ldapsearch -x -H "ldap://${HOST}:${PORT}" -D "${USER}" -y "${LDAP_PASSWORD_FILE}" \
		-LLL -s base -b "cn=failover-group,ou=failover-check,${BASE_DN}" dn >/dev/null 2>>"${LDAP_ERROR_FILE}"
}

case "${MODE}" in
ddl) ddl ;;
marker-write)
	if marker_write; then record marker-write ok; else record marker-write "fail $(grep -v '^WARNING' "${LDAP_ERROR_FILE}" | tail -n 1)"; fi
	;;
marker-read)
	if marker_read; then record marker found; else record marker missing; fi
	;;
idle) idle ;;
memberof-seed)
	if memberof_seed; then record memberof-seed ok; else record memberof-seed "fail $(grep -v '^WARNING' "${LDAP_ERROR_FILE}" | tail -n 1)"; fi
	;;
*)
	record error "unknown-mode-${MODE}"
	;;
esac
echo "probe-done"
exec sleep infinity
