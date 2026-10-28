#!/usr/bin/env bash
# Time window of one rescue-trap step, carved out of the distro budget's kill grace.
#
# Reads:
#   INFINITO_CI_DISTRO_DEADLINE_EPOCH  epoch distros.sh sends the budget SIGTERM at
#   INFINITO_CI_DISTRO_KILL_EPOCH      epoch distros.sh sends the SIGKILL at; unset outside distros.sh
#
# Sets in the caller:
#   rescue_secs   timeout of the step
#   rescue_until  epoch the step must end by; empty while the step keeps its nominal time

# Param: $1 seconds the step takes when the trap was not entered by the budget SIGTERM
rescue_window() {
	local now
	now="$(date +%s)"
	rescue_secs="$1"
	rescue_until=""
	[ -n "${INFINITO_CI_DISTRO_KILL_EPOCH:-}" ] || return 0 # nocheck: distros.sh exports this epoch at run time; a static default would be a stale timestamp
	((now >= INFINITO_CI_DISTRO_DEADLINE_EPOCH)) || return 0
	rescue_secs="$(((INFINITO_CI_DISTRO_KILL_EPOCH - now + 1) / 2))"
	((rescue_secs > 0)) || rescue_secs=1
	rescue_until="$((now + rescue_secs))"
	echo ">>> Budget kill: $((INFINITO_CI_DISTRO_KILL_EPOCH - now))s left until the SIGKILL, ${rescue_secs}s for this rescue step (until epoch ${rescue_until})"
}
