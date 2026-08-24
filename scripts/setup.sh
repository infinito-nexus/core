#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Running project setup (no installation)"

: "${PYTHON:?PYTHON must be set by Makefile (venv python3)}"

echo "🐍 Using PYTHON=${PYTHON}"
if command -v "${PYTHON}" >/dev/null 2>&1; then
	"${PYTHON}" -c 'import sys; print("sys.executable=", sys.executable)' || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

ROLES_DIR="./roles"

require_dir() {
	local path="$1"
	[[ -d "$path" ]] || {
		echo "❌ Directory not found: $path" >&2
		exit 1
	}
}

require_cmd() {
	command -v "$1" >/dev/null || {
		echo "❌ Command not found: $1" >&2
		exit 1
	}
}

require_cmd "${PYTHON}"
require_dir "${ROLES_DIR}"

echo
echo "🎉 Project setup completed"
