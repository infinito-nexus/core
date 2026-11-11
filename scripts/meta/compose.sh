#!/usr/bin/env bash
# shellcheck shell=bash
#
# Sourced. Defines infinito_compose: `docker compose` with the stack's -p and
# -f flags from cli.administration.deploy.development.stack.
# Param cwd: the repository root; the -f paths are relative to it.
# Param argv: forwarded to `docker compose` after the flags.
#
# python.sh is sourced on every call: a `make compose-up` run between two calls
# can create the venv the first call had to fall back from.

_infinito_compose_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

infinito_compose() {
	local flags
	local -a argv
	# shellcheck source=scripts/meta/env/python.sh
	source "${_infinito_compose_root}/scripts/meta/env/python.sh"
	flags="$("${PYTHON}" -m cli.administration.deploy.development.stack)" || return
	mapfile -t argv <<<"${flags}"
	docker compose "${argv[@]}" "$@"
}
