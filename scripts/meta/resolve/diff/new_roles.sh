#!/usr/bin/env bash
# Output: application roles new on this branch (absent at origin/main), space-separated; empty when none or the baseline is unavailable.
set -euo pipefail

PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

git fetch --quiet --no-tags --prune --depth=50 origin main >/dev/null 2>&1 ||
	git fetch --quiet --no-tags --prune origin main >/dev/null 2>&1 || true

"${PYTHON}" -m cli.meta.roles.applications.new_in_branch origin/main
