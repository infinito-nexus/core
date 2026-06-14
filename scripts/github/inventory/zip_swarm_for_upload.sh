#!/usr/bin/env bash
set +e

: "${APP_ID:?APP_ID is required (matrix.apps)}"

out="/tmp/inventory-swarm-${APP_ID}.zip"
if [[ -d /tmp/inv ]]; then
	(cd /tmp && zip -r "${out}" inv)
else
	echo "No inventory found at /tmp/inv"
fi
exit 0
