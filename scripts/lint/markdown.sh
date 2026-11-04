#!/usr/bin/env bash
# shellcheck shell=bash
#
# Run markdownlint-cli2 against the repository.
# Config: .markdownlint-cli2.jsonc at the repo root.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v markdownlint-cli2 >/dev/null 2>&1; then
	echo "markdownlint-cli2 not installed. Run 'make install-lint' first." >&2
	exit 127
fi

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"

if ! lint_diff_active markdown; then
	markdownlint-cli2
	exit
fi

mapfile -t md_files < <(lint_diff_files '\.md$')
if [[ "${#md_files[@]}" -eq 0 ]]; then
	echo "No changed Markdown files."
	exit 0
fi
markdownlint-cli2 --no-globs "${md_files[@]/#/:}"
