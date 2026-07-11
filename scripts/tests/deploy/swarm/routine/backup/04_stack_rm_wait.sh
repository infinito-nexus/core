#!/usr/bin/env bash
# Runs in-node on the manager. Removes the app stack and waits until every
# one of its services is gone so the volume can be wiped safely.
#
# Arguments:
#   $1 STACK_NAME  docker stack to remove
set -euo pipefail

STACK_NAME="${1:?usage: 04_stack_rm_wait.sh STACK_NAME}"

docker stack rm "${STACK_NAME}"
for _ in $(seq 1 90); do
	remaining="$(docker service ls --filter "name=${STACK_NAME}_" --format '{{.Name}}' | wc -l | tr -d ' ')"
	[ "${remaining}" = "0" ] && exit 0
	sleep 2
done
echo "WARNING: ${STACK_NAME} services still listed after 180s; continuing"
