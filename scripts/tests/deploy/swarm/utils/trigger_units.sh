#!/usr/bin/env bash
# Runs in-node. Starts every installed systemd unit matching a pattern.
#
# Arguments:
#   $1 PATTERN  systemd unit glob (e.g. 'svc-bkp-volume-2-local*.service')
#   $2 DUMPS    directory the full journal of a failed unit is written to
#
# Exit codes: 0 all units completed, 1 a unit failed (journal dumped),
# 2 no unit matches the pattern (caller decides whether that is fatal). The
# `|| true` is load-bearing: list-unit-files exits 1 on an empty glob, and
# under pipefail that would kill the script before the exit-2 contract runs.
set -euo pipefail

PATTERN="${1:?usage: trigger_units.sh PATTERN DUMPS}"
DUMPS="${2:?usage: trigger_units.sh PATTERN DUMPS}"

units="$(systemctl list-unit-files "${PATTERN}" --no-legend | awk '{print $1}' || true)"
[ -n "${units}" ] || exit 2

NODE="$(uname -n)"

while read -r unit; do
	[ -n "${unit}" ] || continue
	echo "    starting ${unit} on ${NODE}"
	if ! systemctl start "${unit}"; then
		mkdir -p "${DUMPS}"
		dump="${DUMPS}/${unit}.${NODE}.journal.txt"
		journalctl -u "${unit}" --no-pager -o short-iso >"${dump}" 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		echo "FAILURE: ${unit} did not complete on ${NODE}; full journal at ${dump}"
		journalctl -u "${unit}" --no-pager -o cat -n 40 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		exit 1
	fi
done <<<"${units}"
