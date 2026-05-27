#!/usr/bin/env bash
# shellcheck shell=bash
# Sort the curated string arrays in `.claude/settings.json` ASCII-ascending.
# Wraps utils/claude_settings_sort.py so the entrypoint stays under scripts/.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# Invoke as a module (`python -m`) so the script's `from . import
# PROJECT_ROOT` resolves against the real package, not as a standalone
# script with no parent.
cd -- "${REPO_ROOT}"
exec python3 -m utils.claude.settings_sort "$@"
