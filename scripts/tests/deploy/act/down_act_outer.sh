#!/usr/bin/env bash
set +e

label='ancestor=catthehacker/ubuntu:act-latest'
ids="$(docker ps -aq --filter "${label}")"
if [ -n "${ids}" ]; then
	echo "→ removing act outer container(s): ${ids}"
	# Word-splitting on $ids is intentional: docker rm -f wants each ID as its own argv element.
	# shellcheck disable=SC2086
	docker rm -f ${ids} >/dev/null 2>&1
else
	echo "→ no act outer container present (nothing to do)"
fi
