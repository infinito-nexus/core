#!/usr/bin/env bash
# Start whichever server the flavor built. S1_FLAVOR is baked as ENV because a
# Dockerfile ARG does not survive into the running container.
set -euo pipefail

if [ "${S1_FLAVOR}" = "laya" ]; then
	exec laya-serve
fi

if [ ! -e "${S1_JEFF_MODEL_PATH}/config.json" ]; then
	mkdir -p "${S1_JEFF_MODEL_PATH}"
	cp -a "${S1_JEFF_IMAGE_MODEL_PATH}/." "${S1_JEFF_MODEL_PATH}/"
fi

exec jeff
