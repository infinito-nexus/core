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

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"

if ! lint_diff_active javascript; then
	npx --no-install eslint 'roles/**/files/**/*.js'
	exit
fi

mapfile -t js_files < <(lint_diff_files '^roles/[^/]+/files/.*\.js$')
if [[ "${#js_files[@]}" -eq 0 ]]; then
	echo "No changed JavaScript files."
	exit 0
fi
npx --no-install eslint --no-warn-ignored "${js_files[@]}"
