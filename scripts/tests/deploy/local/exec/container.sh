#!/usr/bin/env bash
set -euo pipefail

# Open an interactive shell in the running infinito container, or execute a
# one-off command inside it when cmd or positional arguments are set.
#
# Usage:
#   scripts/tests/deploy/local/exec/container.sh [command...]  # nocheck: self-path-reference
#
# Environment:
#   INFINITO_DISTRO     arch|debian|ubuntu|fedora|centos
#   INFINITO_CONTAINER  Optional explicit container name
#   cmd                 One-off shell command to run instead of an interactive shell
#
# Examples:
#   scripts/tests/deploy/local/exec/container.sh whoami  # nocheck: self-path-reference
#   cmd='whoami && id' scripts/tests/deploy/local/exec/container.sh  # nocheck: self-path-reference

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../" && pwd)"

usage() {
	cat <<EOF
Usage:
  ${0}
  ${0} [command...]

Environment:
  INFINITO_DISTRO     arch|debian|ubuntu|fedora|centos
  INFINITO_CONTAINER  Optional explicit container name
  cmd                 One-off shell command to run instead of an interactive shell

Examples:
  ${0}
  ${0} whoami
  cmd='whoami && id' ${0}
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
else
	echo "ERROR: missing scripts/meta/env/load.sh" >&2
	exit 2
fi

# defaults.sh exports INFINITO_CONTAINER from INFINITO_DISTRO (single SPOT
# for the formula). Read strictly here — no local re-derivation.
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER not set after sourcing scripts/meta/env/load.sh — bug in defaults.sh?}"
container="${INFINITO_CONTAINER}"

docker_exec_flags=(-i)
if [[ -t 0 && -t 1 ]]; then
	docker_exec_flags=(-it)
fi

if [[ $# -gt 0 ]]; then
	if [[ "${1:-}" == "--" ]]; then
		shift
	fi
	if [[ $# -eq 0 ]]; then
		usage
		exit 2
	fi
	exec docker exec "${docker_exec_flags[@]}" -w "${INFINITO_SRC_DIR}" "${container}" "$@"
fi

if [[ -n "${cmd:-}" ]]; then
	exec docker exec "${docker_exec_flags[@]}" -w "${INFINITO_SRC_DIR}" "${container}" sh -lc "${cmd}"
fi

exec docker exec "${docker_exec_flags[@]}" -w "${INFINITO_SRC_DIR}" "${container}" sh
