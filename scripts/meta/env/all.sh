#!/usr/bin/env bash
# shellcheck shell=bash
#
# Compose all environment resolution modules.

set -euo pipefail

if [[ "${INFINITO_ENV_LOADED:-}" == "1" ]]; then
	return 0
fi
export INFINITO_ENV_LOADED="1"

source "scripts/meta/env/python.sh"
source "scripts/meta/env/runtime.sh"
source "scripts/meta/env/defaults.sh"
source "scripts/meta/env/inventory.sh"
source "scripts/meta/env/github.sh"
source "scripts/meta/env/cache/registry.sh"
source "scripts/meta/env/cache/package.sh"
