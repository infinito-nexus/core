#!/usr/bin/env bash
set -euo pipefail

stack="${1:?stack name required}"

cid="$(container ps --filter "label=com.docker.swarm.service.name=${stack}_mariadb" --format '{{.ID}}' | head -n1)"
if [ -z "${cid}" ]; then
	echo "no-task-container-yet" >&2
	exit 1
fi
state="$(container inspect -f '{{.State.Status}}' "${cid}")"
if [ "${state}" != "running" ]; then
	echo "task-state=${state}" >&2
	exit 1
fi
printf '%s' "${cid}"
