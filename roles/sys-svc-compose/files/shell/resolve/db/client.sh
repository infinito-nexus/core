#!/bin/bash
# Param: STACK   - swarm stack of the HA engine (e.g. postgres)
# Param: ENGINE  - engine word; instance services are <STACK>_<ENGINE>-<host-id>
# Param: NETWORK - attachable engine network the write endpoint answers on
# Param: CLIENT  - client binary inside the engine image (psql, mariadb)
# Param: ARGS    - every further argument goes to the client unchanged
# Param: PGPASSWORD / MYSQL_PWD - passed into the client container by name only
#
# Exit codes:
#   64  missing args
#   65  the stack runs no instance service of the engine
#   otherwise the client's own exit code
set -eu

STACK="${1:-}"
ENGINE="${2:-}"
NETWORK="${3:-}"
CLIENT="${4:-}"
if [ -z "$STACK" ] || [ -z "$ENGINE" ] || [ -z "$NETWORK" ] || [ -z "$CLIENT" ]; then
	echo "db-client: STACK, ENGINE, NETWORK and CLIENT required" >&2
	exit 64
fi
shift 4

IMAGE="$(container service ls \
	--filter "label=com.docker.stack.namespace=${STACK}" \
	--format '{{.Name}} {{.Image}}' |
	awk -v prefix="${STACK}_${ENGINE}-" 'index($1, prefix) == 1 { print $2; exit }')"
[ -n "$IMAGE" ] || {
	echo "db-client: no instance service '${STACK}_${ENGINE}-*' in stack '${STACK}'" >&2
	exit 65
}

exec container run --rm -i --network "$NETWORK" \
	-e PGPASSWORD -e MYSQL_PWD \
	--entrypoint "$CLIENT" "$IMAGE" "$@"
