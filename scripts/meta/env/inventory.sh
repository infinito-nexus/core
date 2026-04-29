#!/usr/bin/env bash
# shellcheck shell=bash
#
# Resolve inventory path.

set -euo pipefail

if [[ "${INFINITO_ENV_INVENTORY_LOADED:-}" == "1" ]]; then
	return 0
fi
export INFINITO_ENV_INVENTORY_LOADED="1"

: "${RUNNING_ON_ACT:=false}"
: "${RUNNING_ON_GITHUB:=false}"

if [[ -z "${INVENTORY_DIR:-}" ]]; then
	INVENTORY_DIR="$(
		RUNNING_ON_ACT="${RUNNING_ON_ACT}" \
			RUNNING_ON_GITHUB="${RUNNING_ON_GITHUB}" \
			HOME="${HOME:-}" \
			bash scripts/inventory/resolve.sh
	)"
fi
export INVENTORY_DIR

# SPOT: canonical path to the generated inventory devices file.
INVENTORY_FILE="${INVENTORY_DIR}/devices.yml"
export INVENTORY_FILE

# SPOT: canonical path to the host_vars file for localhost.
HOST_VARS_FILE="${INVENTORY_DIR}/host_vars/localhost.yml"
export HOST_VARS_FILE

# SPOT: canonical repo-relative path to the development vars file that
# `infinito create inventory --vars-file <...>` consumes. Anything that
# would otherwise hard-code "inventories/development/default.yml" MUST
# read this variable instead. The Python side mirrors this default in
# cli.deploy.development.common.DEV_INVENTORY_VARS_FILE; a unit test
# locks both literals together so they cannot silently drift.
INVENTORY_VARS_FILE="${INVENTORY_VARS_FILE:-inventories/development/default.yml}"
export INVENTORY_VARS_FILE
