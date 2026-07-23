#!/usr/bin/env bash
# Run cmd inside a swarm SERVICE container on a DinD node.
# Env: node (DinD node container), service (swarm service name), cmd.
set -euo pipefail

: "${node:?node= must be set, e.g. node=web-app-moodle-swarm-mgr-01}"
: "${service:?service= must be set, e.g. service=moodle_moodle}"
: "${cmd:?cmd= must be set, e.g. cmd='php admin/cli/cfg.php --name=...'}"

if ! docker inspect --format '{{.State.Running}}' "${node}" 2>/dev/null | grep -q '^true$'; then
	echo "ERROR: node '${node}' is not running." >&2
	exit 1
fi

enc="$(printf '%s' "${cmd}" | base64 | tr -d '\n')"

docker exec -i -e SVC="${service}" -e ENC="${enc}" "${node}" bash --noprofile --norc -c '
	set -euo pipefail
	cid="$(docker ps -q -f "name=${SVC}" | head -n1)"
	test -n "${cid}" || { echo "ERROR: no running container for service ${SVC}" >&2; exit 1; }
	docker exec -i "${cid}" sh -c "echo \"${ENC}\" | base64 -d | sh"
'
