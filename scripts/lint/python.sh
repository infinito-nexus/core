#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

RUFF_CACHE_DIR="build/ruff-cache-$(id -u)"
export RUFF_CACHE_DIR

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"
mapfile -t custom_roles < <(lint_custom_roles)

shfmt -w scripts
ruff format . "${custom_roles[@]}"
ruff check . --fix "${custom_roles[@]}"
