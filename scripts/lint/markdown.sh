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

markdownlint-cli2
