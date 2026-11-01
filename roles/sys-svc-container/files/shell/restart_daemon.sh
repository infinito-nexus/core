#!/usr/bin/env bash
# Param: SWARM_NODE     - "true" in swarm mode; a node that was active in the swarm before the restart is waited for
# Param: SETTLE_TIMEOUT - seconds the node may take to rejoin the swarm and bring its containers past health "starting"
set -euo pipefail

: "${SWARM_NODE:?}"
: "${SETTLE_TIMEOUT:?}"

was_active=false
if [ "${SWARM_NODE}" = "true" ] && [ "$(container info --format '{{.Swarm.LocalNodeState}}')" = "active" ]; then
	was_active=true
fi

systemctl enable docker.service
systemctl restart docker.service

[ "${was_active}" = "true" ] || exit 0

deadline=$((SECONDS + SETTLE_TIMEOUT))
until [ "$(container info --format '{{.Swarm.LocalNodeState}}')" = "active" ]; do
	if [ "${SECONDS}" -ge "${deadline}" ]; then
		echo "the node did not rejoin the swarm within ${SETTLE_TIMEOUT}s" >&2
		exit 1
	fi
	sleep 2
done
until [ -z "$(container ps -q --filter health=starting)" ]; do
	if [ "${SECONDS}" -ge "${deadline}" ]; then
		echo "containers still starting after ${SETTLE_TIMEOUT}s: $(container ps --filter health=starting --format '{{.Names}}' | tr '\n' ' ')" >&2
		exit 1
	fi
	sleep 2
done
