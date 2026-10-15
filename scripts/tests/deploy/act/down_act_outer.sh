#!/usr/bin/env bash
set +e

: "${INFINITO_CONTAINER:?INFINITO_CONTAINER is not set; source scripts/meta/env/load.sh or invoke via make}"

ids="$(docker ps -aq --filter "name=^act-" --filter "label=infinito.worktree=${INFINITO_CONTAINER}")"
if [ -n "${ids}" ]; then
	echo "→ removing act outer container(s) of ${INFINITO_CONTAINER}: ${ids}"
	# shellcheck disable=SC2086
	docker rm -f ${ids} >/dev/null 2>&1
else
	echo "→ no act outer container present (nothing to do)"
fi

exit 0
