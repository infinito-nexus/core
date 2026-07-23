#!/usr/bin/env bash
# Runs in-node. Starts every installed systemd unit matching a pattern.
#
# Arguments:
#   $1 PATTERN  systemd unit glob (e.g. 'svc-bkp-volume-2-local*.service')
#
# Exit codes: 0 all units completed, 1 a unit failed (journal dumped),
# 2 no unit matches the pattern (caller decides whether that is fatal). The
# `|| true` is load-bearing: list-unit-files exits 1 on an empty glob, and
# under pipefail that would kill the script before the exit-2 contract runs.
set -euo pipefail

PATTERN="${1:?usage: trigger_units.sh PATTERN}"

units="$(systemctl list-unit-files "${PATTERN}" --no-legend | awk '{print $1}' || true)"
[ -n "${units}" ] || exit 2

while read -r unit; do
	[ -n "${unit}" ] || continue
	echo "    starting ${unit} on $(hostname)"
	if ! systemctl start "${unit}"; then
		echo "FAILURE: ${unit} did not complete on $(hostname); journal:"
		journalctl -u "${unit}" --no-pager -n 60 2>/dev/null || true
		exit 1
	fi
done <<<"${units}"
