#!/usr/bin/env bash
# Start whichever server the flavor built. S1_FLAVOR is baked as ENV because a
# Dockerfile ARG does not survive into the running container.
set -euo pipefail

if [ "${S1_FLAVOR}" = "laya" ]; then
	exec laya-serve
fi

exec jeff
