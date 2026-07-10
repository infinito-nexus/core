#!/usr/bin/env bash
# Snapshot the pre-deploy state through the backup unit the PREVIOUS deploy
# installed, before this deploy mutates anything. A missing unit or an empty
# source means a fresh host with nothing to save yet. Unit names embed the
# project version, so after a version bump the previous deploy's unit differs
# from the requested name; fall back to a same-base glob and start the newest
# installed version. SOURCE is the file (databases.csv) or directory (export
# base) whose emptiness marks a not-yet-seeded host.
set -euo pipefail

UNIT="${1:?usage: pre_deploy_snapshot.sh <backup-unit-name> <source-path>}"
SOURCE="${2:?usage: pre_deploy_snapshot.sh <backup-unit-name> <source-path>}"

source_has_content() {
    local src="$1"
    if [[ -f "${src}" ]]; then
        [[ -s "${src}" ]]
    elif [[ -d "${src}" ]]; then
        [[ -n "$(find "${src}" -mindepth 1 -print -quit 2>/dev/null)" ]]
    else
        return 1
    fi
}

if ! systemctl cat "${UNIT}" >/dev/null 2>&1; then
    BASE="${UNIT%%.*}"
    if unit_files="$(systemctl list-unit-files --no-legend "${BASE}.*.service" 2>/dev/null)"; then
        UNIT="$(printf '%s\n' "${unit_files}" | awk 'NF {print $1}' | sort | tail -n1)"
    else
        UNIT=""
    fi
    if [[ -z "${UNIT}" ]]; then
        echo "SKIP: no ${BASE}.* unit installed yet (fresh host)"
        exit 0
    fi
fi

if ! source_has_content "${SOURCE}"; then
    echo "SKIP: ${SOURCE} missing or empty (nothing to back up yet)"
    exit 0
fi

echo "Starting ${UNIT} for the pre-deploy snapshot..."
systemctl start "${UNIT}"
echo "OK: pre-deploy snapshot finished"
