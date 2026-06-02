#!/usr/bin/env bash
set -euo pipefail

stack_service="${1:?stack_service required (e.g. mediawiki_mediawiki)}"
require_running="${2:-true}"

cid="$(container ps --filter "label=com.docker.swarm.service.name=${stack_service}" --format '{{.ID}}' | head -n1)"
if [ -z "${cid}" ]; then
	echo "no-task-container-yet" >&2
	exit 1
fi
if [ "${require_running}" = "true" ]; then
	state="$(container inspect -f '{{.State.Status}}' "${cid}")"
	if [ "${state}" != "running" ]; then
		echo "task-state=${state}" >&2
		exit 1
	fi
fi
printf '%s' "${cid}"
