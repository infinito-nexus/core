#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# 🐍 Virtualenv bootstrap & setup
#
# This script is responsible for creating the Python virtualenv
# used by the entire Infinito.Nexus toolchain.
#
# Important design rule:
#   ❗ The venv Python interpreter CANNOT be used before the venv exists.
#   ❗ Therefore we must bootstrap using system python3 first.
#
# Lifecycle:
#   1) Use system python3 to create the venv
#   2) Afterwards, Makefile provides PYTHON=${VENV}/bin/python
#   3) All tooling runs inside the venv from then on
#
# This avoids chicken-and-egg failures in CI and on fresh machines.
# ------------------------------------------------------------

: "${VENV:?VENV not set (e.g. /opt/venvs/infinito)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEV_PYTHON_INSTALLER="${REPO_ROOT}/roles/dev-python/files/install.sh"

install_venv() {
	if [[ ! -f "${DEV_PYTHON_INSTALLER}" ]]; then
		echo "❌ Missing installer: ${DEV_PYTHON_INSTALLER}" >&2
		return 1
	fi

	# 🛠 Bootstrap interpreter (system Python, outside of venv)
	# Used ONLY to CREATE the virtualenv.
	local bootstrap_python
	bootstrap_python="$(bash "${DEV_PYTHON_INSTALLER}" print)"

	# 📦 Target interpreter inside the venv (may not exist yet!)
	local venv_python="${VENV}/bin/python"

	echo "🐍 Virtualenv target  : ${VENV}"
	echo "🛠 Bootstrap python   : ${bootstrap_python}"
	echo "🎯 Venv python target : ${venv_python}"
	echo

	# Probe dirname(VENV) so a non-writable legacy path can't trigger a spurious sudo (fatal under no_new_privs sandboxes).
	local venv_parent
	venv_parent="$(dirname "${VENV}")"
	if [[ -n "${VIRTUAL_ENV:-}" && "${VIRTUAL_ENV}" == "${VENV}" ]]; then
		: # active venv matches the target; nothing to prepare
	elif [[ -d "${venv_parent}" && -w "${venv_parent}" ]]; then
		: # venv parent exists and is writable; nothing to prepare
	elif [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
		mkdir -p "${venv_parent}"
	else
		sudo mkdir -p "${venv_parent}"
		sudo chown "${USER:-$(whoami)}" "${venv_parent}"
	fi

	# ------------------------------------------------------------
	# Create venv if missing
	# ------------------------------------------------------------
	if [[ ! -x "${venv_python}" ]]; then
		echo "→ Creating virtualenv ${VENV}"
		"${bootstrap_python}" -m venv "${VENV}"
		echo "✅ Virtualenv created"
	else
		echo "→ Virtualenv already exists"
	fi
}

install_venv
