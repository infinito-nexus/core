#!/usr/bin/env bash
# shellcheck shell=bash
#
# Lint the project Makefile via mbake (https://github.com/EbodShojaei/bake).
# Reports formatting drift and missing .PHONY declarations against
# referenced rule names. Auto-fix lives in scripts/lint/autoformat.sh.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v mbake >/dev/null 2>&1; then
	echo "mbake not installed. Run 'make install-lint' first." >&2
	exit 127
fi

mbake format --check Makefile
