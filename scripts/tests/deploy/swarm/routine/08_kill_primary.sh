#!/usr/bin/env bash
# Param:
#   INFINITO_CI_KILL_PRIMARY     "true" runs the probe; anything else skips it
#   INFINITO_SWARM_DB_TOPOLOGY   must be "ha"; a standalone row is never touched
#   SWARM_LAB_MANAGERS           space-separated manager node containers
#   KILL_PRIMARY_TIMEOUT         seconds to wait for failover and the app (default 300)
set -euo pipefail

if [ "${INFINITO_CI_KILL_PRIMARY}" != "true" ] || [ "${INFINITO_SWARM_DB_TOPOLOGY}" != "ha" ]; then
	echo "SKIP: kill-primary probe runs only on HA rows with INFINITO_CI_KILL_PRIMARY=true"
	exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../utils/_context.sh"

skip_if_no_swarm_service

if [ -z "${HA_DEPS}" ]; then
	echo "SKIP: ${APP_ID} uses no central HA engine"
	exit 0
fi

: "${SWARM_LAB_MANAGERS:?SWARM_LAB_MANAGERS required}"
KILL_PRIMARY_TIMEOUT="${KILL_PRIMARY_TIMEOUT:-300}"
read -r -a MANAGERS <<<"${SWARM_LAB_MANAGERS}"
CTL="${MGR}"

# Param: $1 node container to avoid
# Sets CTL to a manager other than $1.
pick_controller() {
	local _m
	for _m in "${MANAGERS[@]}"; do
		if [ "${_m}" != "$1" ]; then
			CTL="${_m}"
			return 0
		fi
	done
	echo "FAILURE: no manager left besides $1" >&2
	exit 1
}

# Param: $1 engine
# Prints the engine's per-host instance services, sentinels excluded.
instance_services() {
	docker exec "${CTL}" docker service ls --format '{{.Name}}' |
		grep -E "^$1_$1-" | grep -vE "^$1_$1-sentinel-" || [ "$?" -eq 1 ]
}

# Param: $1 instance swarm service name
# Prints "<node> <cid>" of the instance's running task, or nothing.
instance_location() {
	local _node _cid
	_node=$(docker exec "${CTL}" docker service ps --filter desired-state=running \
		--format '{{.Node}}' "$1" 2>/dev/null | head -1)
	[ -n "${_node}" ] || return 0
	_cid=$(service_container_id "${_node}" "$1" 2>/dev/null || true)
	if [ -n "${_cid}" ]; then
		echo "${_node} ${_cid}"
	fi
}

# Param: $1 engine, $2 node container, $3 instance swarm service name (<stack>_<key>)
is_primary() {
	docker exec "$2" "primary-probe-$1" "${3%%_*}" "${3#*_}" >/dev/null 2>&1
}

# Param: $1 engine
# Prints "<node> <cid> <service>" of the current primary, or nothing.
find_primary() {
	local _svc _loc
	for _svc in $(instance_services "$1"); do
		_loc=$(instance_location "${_svc}")
		[ -n "${_loc}" ] || continue
		if is_primary "$1" "${_loc%% *}" "${_svc}"; then
			echo "${_loc} ${_svc}"
			return 0
		fi
	done
}

# Param: $1 engine, $2 node container, $3 instance container id, $4 unique stamp
write_through_endpoint() {
	case "$1" in
	postgres)
		docker exec "$2" docker exec "$3" sh -c '
			PGPASSWORD="$POSTGRES_PASSWORD" psql -h postgres -U postgres -d postgres -qAt \
				-c "CREATE TABLE IF NOT EXISTS kill_primary_probe (stamp bigint PRIMARY KEY)" \
				-c "INSERT INTO kill_primary_probe VALUES ($1)"' _ "$4"
		;;
	mariadb)
		docker exec "$2" docker exec "$3" sh -c '
			MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -h mariadb -u root \
				-e "CREATE DATABASE IF NOT EXISTS kill_primary_probe; CREATE TABLE IF NOT EXISTS kill_primary_probe.probe (stamp BIGINT PRIMARY KEY); INSERT INTO kill_primary_probe.probe VALUES ($1)"' _ "$4"
		;;
	redis)
		docker exec "$2" docker exec "$3" sh -c '
			[ "$(REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h redis SET "kill-primary-probe:$1" 1)" = OK ]' _ "$4"
		;;
	openldap)
		docker exec "$2" docker exec "$3" sh -c '
			f=$(mktemp)
			printf %s "$LDAP_ROOT_PW" >"$f"
			printf "dn: cn=kill-primary-probe-%s,%s\nobjectClass: device\ncn: kill-primary-probe-%s\n" "$1" "$LDAP_SUFFIX" "$1" |
				ldapadd -x -H ldap://openldap:389 -D "$LDAP_ROOT_DN" -y "$f"
			rc=$?
			rm -f "$f"
			exit "$rc"' _ "$4"
		;;
	esac
}

# Param: $1 node container
is_manager() {
	local _m
	for _m in "${MANAGERS[@]}"; do
		[ "${_m}" != "$1" ] || return 0
	done
	return 1
}

# Param: $1 node container about to be killed
# Succeeds when the managers left after killing $1 still hold the Raft quorum.
keeps_quorum() {
	local _total="${#MANAGERS[@]}" _left="${#MANAGERS[@]}"
	if is_manager "$1"; then
		_left=$((_total - 1))
	fi
	[ $((_left * 2)) -gt "${_total}" ]
}

# Param: $1 node container about to be killed
# Succeeds when the app may only run on $1.
app_pinned_to() {
	[ "${DEFAULT_PLACEMENT_MANAGER}" = "true" ] &&
		[ "${#MANAGERS[@]}" -gt 1 ] &&
		[ "$1" = "${MANAGERS[0]}" ]
}

NAME_FILES=(/etc/resolv.conf /etc/hosts)
NAME_FILES_DIR="$(mktemp -d)"
trap 'rm -rf "${NAME_FILES_DIR}"' EXIT

# Param: $1 node container
save_name_files() {
	local _path
	for _path in "${NAME_FILES[@]}"; do
		docker exec "$1" cat "${_path}" >"${NAME_FILES_DIR}/$(basename "${_path}")"
	done
}

# Param: $1 node container
restore_name_files() {
	local _path
	for _path in "${NAME_FILES[@]}"; do
		docker exec -i "$1" sh -c 'cat >"$1"' _ "${_path}" <"${NAME_FILES_DIR}/$(basename "${_path}")"
	done
}

# Param: $1 node container
# Prints how many tasks of the services pinned to $1 run there.
pinned_tasks_running() {
	local _names
	if ! _names=$(docker exec "$1" docker ps --filter status=running --format '{{.Names}}' 2>/dev/null); then
		echo 0
		return 0
	fi
	printf '%s\n' "${_names}" | awk -v marker="-$1." 'index($0, marker) { n++ } END { print n + 0 }'
}

# Param: $1 node container, $2 pinned tasks it ran before the kill
restart_node() {
	local _deadline _running
	docker start "$1" >/dev/null
	restore_name_files "$1"
	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	while [ "$(date +%s)" -lt "${_deadline}" ]; do
		_running=$(pinned_tasks_running "$1")
		if [ "${_running}" -ge "$2" ]; then
			echo "==> $1 rejoined the swarm and runs its ${_running} pinned tasks again"
			return 0
		fi
		sleep 3
	done
	echo "FAILURE: $1 runs ${_running} of its $2 pinned tasks ${KILL_PRIMARY_TIMEOUT}s after the restart"
	docker exec "${CTL}" docker node ls
	docker exec "$1" docker info --format '{{json .Swarm}}'
	docker exec "$1" journalctl -u docker --no-pager -n 80
	exit 1
}

# Param: $1 engine
# Succeeds when every per-host service of $1 and every etcd member runs its task.
at_full_strength() {
	local _replicas
	_replicas=$(docker exec "${CTL}" docker service ls --format '{{.Name}} {{.Replicas}}' |
		grep -E "^($1_$1|etcd_etcd)-" || [ "$?" -eq 1 ])
	[ -n "${_replicas}" ] && ! grep -qvE ' 1/1( |$)' <<<"${_replicas}"
}

# Param: $1 engine
wait_full_strength() {
	local _deadline
	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	until at_full_strength "$1"; do
		if [ "$(date +%s)" -ge "${_deadline}" ]; then
			echo "FAILURE: $1 and etcd not at full strength within ${KILL_PRIMARY_TIMEOUT}s before the kill"
			docker exec "${CTL}" docker service ls --format '{{.Name}} {{.Replicas}}' |
				grep -E "^($1_$1|etcd_etcd)-" || [ "$?" -eq 1 ]
			exit 1
		fi
		sleep 3
	done
}

# Param: $1 node container, $2 redis instance container id
# Succeeds when every Sentinel answers with one and the same master.
sentinels_agree() {
	docker exec "$1" docker exec "$2" sh -c '
		REDISCLI_AUTH=$(cat "$REDIS_HA_SENTINEL_PASSWORD_FILE")
		export REDISCLI_AUTH
		seen=""
		for s in $REDIS_HA_SENTINELS; do
			m=$(timeout 3 redis-cli -h "$s" -p "$REDIS_HA_SENTINEL_PORT" --raw \
				SENTINEL get-master-addr-by-name "$REDIS_HA_MASTER_NAME" 2>/dev/null | head -1)
			[ -n "$m" ] || exit 1
			[ -z "$seen" ] || [ "$m" = "$seen" ] || exit 1
			seen=$m
		done' >/dev/null 2>&1
}

wait_sentinels_agree() {
	local _deadline _loc
	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	while [ "$(date +%s)" -lt "${_deadline}" ]; do
		_loc=$(instance_location "$(instance_services redis | head -1)")
		# shellcheck disable=SC2086  # _loc is "<node> <cid>", split into sentinels_agree's args
		if [ -n "${_loc}" ] && sentinels_agree ${_loc}; then
			return 0
		fi
		sleep 3
	done
	echo "FAILURE: the redis Sentinels did not agree on one master within ${KILL_PRIMARY_TIMEOUT}s before the kill"
	exit 1
}

# Param: $1 engine, $2 node container, $3 primary instance container id
# Succeeds when every other instance of a redis primary replicates from it.
replicas_attached() {
	local _want
	[ "$1" = redis ] || return 0
	_want=$(($(instance_services "$1" | wc -l) - 1))
	docker exec "$2" docker exec "$3" sh -c '
		REDISCLI_AUTH=$(sed -n "s/^masterauth //p" "$REDIS_HA_INCLUDE")
		export REDISCLI_AUTH
		n=$(redis-cli -p "$REDIS_HA_PORT" INFO replication | sed -n "s/^connected_slaves:\([0-9]*\).*/\1/p")
		[ "${n:-0}" -ge "$1" ]' _ "${_want}" >/dev/null 2>&1
}

# Param: $1 engine
# Prints "<node> <cid> <service>" of the primary once its replicas are attached,
# or nothing after KILL_PRIMARY_TIMEOUT.
wait_primary() {
	local _deadline _primary
	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	while [ "$(date +%s)" -lt "${_deadline}" ]; do
		_primary=$(find_primary "$1" || true)
		# shellcheck disable=SC2086  # ${_primary% *} is "<node> <cid>", split into replicas_attached's args
		if [ -n "${_primary}" ] && replicas_attached "$1" ${_primary% *}; then
			echo "${_primary}"
			return 0
		fi
		sleep 3
	done
}

# Param: $1 "<node> <cid> <service>" of the current primary, $2 container id that was killed
# Succeeds when the primary runs in a container other than $2.
restarted_in_place() {
	local _cid
	[ -n "$1" ] || return 1
	read -r _ _cid _ <<<"$1"
	[ "${_cid}" != "$2" ]
}

# Param: $1 engine
kill_primary_of() {
	local _engine="$1" _dep _old _old_node _old_cid _old_service _killed_node="" _pinned=0 _new="" _deadline _stamp _write_err=""
	if [ -z "$(instance_services "${_engine}")" ]; then
		echo "SKIP: ${_engine} runs no HA instances for ${APP_ID}"
		return 0
	fi
	for _dep in ${HA_DEPS}; do
		[ -n "$(instance_services "${_dep}")" ] || continue
		wait_full_strength "${_dep}"
		if [ "${_dep}" = redis ]; then
			wait_sentinels_agree
		fi
	done
	echo "==> every HA engine and etcd at full strength"
	_old=$(wait_primary "${_engine}")
	if [ -z "${_old}" ]; then
		echo "FAILURE: no ${_engine} primary with every replica attached within ${KILL_PRIMARY_TIMEOUT}s before the kill"
		exit 1
	fi
	read -r _old_node _old_cid _old_service <<<"${_old}"
	echo "==> ${_engine} primary is ${_old_service} on ${_old_node}"

	if ! keeps_quorum "${_old_node}"; then
		docker exec "${_old_node}" docker kill "${_old_cid}" >/dev/null
		echo "==> killing ${_old_node} would lose the Raft quorum; killed the ${_engine} container instead"
	elif app_pinned_to "${_old_node}"; then
		docker exec "${_old_node}" docker kill "${_old_cid}" >/dev/null
		echo "==> ${APP_ID} is pinned to ${_old_node}; killed the ${_engine} container instead of the node"
	else
		pick_controller "${_old_node}"
		save_name_files "${_old_node}"
		_pinned=$(pinned_tasks_running "${_old_node}")
		docker kill "${_old_node}" >/dev/null
		_killed_node="${_old_node}"
		echo "==> killed node ${_old_node}"
	fi

	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	while [ "$(date +%s)" -lt "${_deadline}" ]; do
		_new=$(find_primary "${_engine}" || true)
		if [ -n "${_new}" ] && [ "${_new##* }" != "${_old_service}" ]; then
			echo "==> new ${_engine} primary: ${_new##* } on ${_new%% *}"
			break
		fi
		if [ -z "${_killed_node}" ] && restarted_in_place "${_new}" "${_old_cid}"; then
			echo "==> ${_engine} primary ${_new##* } came back in a fresh container on ${_new%% *}"
			break
		fi
		_new=""
		sleep 3
	done
	[ -n "${_new}" ] || {
		echo "FAILURE: no new ${_engine} primary within ${KILL_PRIMARY_TIMEOUT}s"
		exit 1
	}

	_stamp="$(date +%s%N)"
	# shellcheck disable=SC2086  # ${_new% *} is "<node> <cid>", split into write_through_endpoint's args
	while ! _write_err=$(write_through_endpoint "${_engine}" ${_new% *} "${_stamp}" 2>&1); do
		if [ "$(date +%s)" -ge "${_deadline}" ]; then
			echo "FAILURE: no write through the ${_engine} endpoint within ${KILL_PRIMARY_TIMEOUT}s after the kill"
			echo "last write error: ${_write_err}"
			exit 1
		fi
		sleep 3
	done
	echo "==> write through the ${_engine} endpoint succeeded after the kill"

	if [ -n "${_killed_node}" ] && [ "${_killed_node}" = "${MANAGERS[0]}" ]; then
		restart_node "${_killed_node}" "${_pinned}"
		wait_app_reachable "" "${_engine}"
		return 0
	fi

	wait_app_reachable "${_killed_node}" "${_engine}"

	if [ -n "${_killed_node}" ]; then
		restart_node "${_killed_node}" "${_pinned}"
	fi
}

# Param: $1 node container that was killed, empty when only the engine container was; $2 engine
wait_app_reachable() {
	local _deadline _app_node _app_ctr
	_deadline=$(($(date +%s) + KILL_PRIMARY_TIMEOUT))
	while [ "$(date +%s)" -lt "${_deadline}" ]; do
		_app_node=$(docker exec "${CTL}" docker service ps --filter desired-state=running \
			--format '{{.Node}}' "${SERVICE_NAME}" 2>/dev/null | grep -vxF "$1" | head -1 || true)
		if [ -n "${_app_node}" ]; then
			_app_ctr=$(service_container_id "${_app_node}" "${SERVICE_NAME}" 2>/dev/null || true)
			if [ -n "${_app_ctr}" ] && probe_app_reachable "${_app_node}" "${_app_ctr}" "${PROBE_PORT}"; then
				echo "${ENTITY} reachable after the $2 primary was killed"
				return 0
			fi
		fi
		sleep 3
	done
	echo "FAILURE: ${ENTITY} not reachable within ${KILL_PRIMARY_TIMEOUT}s after the $2 primary was killed"
	exit 1
}

for engine in ${HA_DEPS}; do
	kill_primary_of "${engine}"
done
