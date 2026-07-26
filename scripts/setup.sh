#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Running project setup (no installation)"

: "${PYTHON:?PYTHON must be set by Makefile (venv python3)}"

echo "🐍 Using PYTHON=${PYTHON}"
if command -v "${PYTHON}" >/dev/null 2>&1; then
	"${PYTHON}" -c 'import sys; print("sys.executable=", sys.executable)' || true
fi

ROLES_DIR="./roles"

INCLUDES_SCRIPT="./cli/build/include/__main__.py"
INCLUDES_OUT_DIR="./tasks/groups"

# ------------------------------------------------------------
# Validation
# ------------------------------------------------------------
require_file() {
	local path="$1"
	[[ -f "$path" ]] || {
		echo "❌ File not found: $path" >&2
		exit 1
	}
}

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
require_file "${INCLUDES_SCRIPT}"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
log_section() {
	echo
	echo "------------------------------------------------------------"
	echo "$1"
	echo "------------------------------------------------------------"
}

log_section "🧩 Generating role include files"
mkdir -p "${INCLUDES_OUT_DIR}"

mapfile -t INCLUDE_GROUPS < <("${PYTHON}" -m cli.meta.categories.invokable -s "-")

for existing in "${INCLUDES_OUT_DIR}"/*-roles.yml; do
	[[ -e "${existing}" ]] || continue
	keep=0
	for grp in "${INCLUDE_GROUPS[@]}"; do
		[[ "${existing}" == "${INCLUDES_OUT_DIR}/${grp}roles.yml" ]] && keep=1
	done
	if [[ "${keep}" -eq 0 ]]; then
		echo "→ Removing stale ${existing}"
		rm -f "${existing}"
	fi
done

for grp in "${INCLUDE_GROUPS[@]}"; do
	[[ -z "${grp}" ]] && continue
	out="${INCLUDES_OUT_DIR}/${grp}roles.yml"
	echo "→ Building ${out} (pattern: '${grp}')"
	"${PYTHON}" "${INCLUDES_SCRIPT}" "${ROLES_DIR}" -p "${grp}" -o "${out}"
	echo "  ✅ ${out}"
done

echo
echo "🎉 Project setup completed"
