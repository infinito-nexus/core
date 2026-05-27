#!/usr/bin/env bash
# shellcheck shell=bash
#
# SPOT for venv + Python interpreter resolution. Exports VENV, PYTHON,
# PIP, PYTHONPATH. Sourced; re-entrant.

VENV_NAME=infinito

if [[ -z "${VENV:-}" ]]; then
	for _venv_candidate in "/opt/venvs/${VENV_NAME}" "${HOME}/.venvs/${VENV_NAME}"; do
		if [[ -x "${_venv_candidate}/bin/python" ]]; then
			VENV="${_venv_candidate}"
			break
		fi
	done
	unset _venv_candidate
fi

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
	VENV_BASE="$(dirname "${VIRTUAL_ENV}")"
elif [[ -d /opt && -w /opt ]]; then
	VENV_BASE=/opt/venvs
else
	VENV_BASE="${HOME}/.venvs"
fi

VENV_FALLBACK="${VENV_BASE%/}/${VENV_NAME}"
VENV="${VENV:-${VIRTUAL_ENV:-${VENV_FALLBACK}}}"

if [[ -x "${VENV}/bin/python" ]]; then
	PYTHON="${VENV}/bin/python"
elif command -v python3 >/dev/null 2>&1; then
	PYTHON=python3
else
	echo "detect.sh: no python3 on PATH and no venv at ${VENV}/bin/python" >&2
	# shellcheck disable=SC2317
	return 1 2>/dev/null || exit 1
fi

PIP="${PYTHON} -m pip"
PYTHONPATH="${PYTHONPATH:-.}"

export VENV PYTHON PIP PYTHONPATH
