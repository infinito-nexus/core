#!/usr/bin/env bash
# shellcheck shell=bash
#
# Run ESLint against the project's JavaScript files (Playwright specs +
# persona helpers). Config: eslint.config.js at the repo root.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -d "node_modules/eslint" ]]; then
	echo "ESLint not installed. Run 'make install-lint' first." >&2
	exit 127
fi

npx --no-install eslint 'roles/**/files/**/*.js'
