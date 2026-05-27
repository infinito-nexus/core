#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run a one-off `docker run` INSIDE the infinito host container
# (which already provides nested Docker-in-Docker). Used for inner-loop
# debugging where you need to spin up a sidecar image (e.g. the Playwright
# runner) against the same docker daemon the deployed stack lives on,
# without re-running an Ansible playbook.
#
# Required env:
#   IMAGE              Image reference passed to `docker run` (e.g. alpine,
#                      mcr.microsoft.com/playwright:v1.59.1-noble)
#
# Optional env:
#   cmd                Command to execute inside the sidecar container.
#                      When omitted, the image's default entrypoint runs.
#   INFINITO_RUN_FLAGS          Extra flags forwarded verbatim to `docker run`
#                      (e.g. "--env-file /tmp/x.env -v /tmp/y:/y -w /e2e").
#   INFINITO_DISTRO    arch|debian|ubuntu|fedora|centos — selects which
#                      infinito host container we exec into.
#   INFINITO_CONTAINER Optional explicit override of the host container name.
#
# Examples:
#   IMAGE=alpine make compose-inner-run
#   IMAGE=alpine cmd='env | grep PATH' make compose-inner-run
#   IMAGE=mcr.microsoft.com/playwright:v1.59.1-noble \
#     INFINITO_RUN_FLAGS='--env-file /tmp/test-e2e-playwright/web-app-friendica/.env \
#                -v /tmp/test-e2e-playwright/web-app-friendica:/e2e -w /e2e' \
#     cmd='npx playwright test --grep dashboard' \
#     make compose-inner-run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../" && pwd)"

usage() {
	cat <<EOF
Usage:
  IMAGE=<ref> [cmd='<shell>'] [INFINITO_RUN_FLAGS='<flags>'] ${0}

Examples:
  IMAGE=alpine ${0}
  IMAGE=alpine cmd='env' ${0}
  IMAGE=mcr.microsoft.com/playwright:v1.59.1-noble \\
    INFINITO_RUN_FLAGS='--env-file /tmp/.env -v /tmp/proj:/e2e -w /e2e' \\
    cmd='npx playwright test' \\
    ${0}
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

: "${IMAGE:?IMAGE must be set (e.g. IMAGE=alpine)}"

cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"
: "${INFINITO_CONTAINER:?INFINITO_CONTAINER not set after sourcing scripts/meta/env/load.sh}"

# Build the nested `docker run` argv. Splitting INFINITO_RUN_FLAGS on whitespace is
# intentional — same UX as INFINITO_RUN_FLAGS in any other Make wrapper. Callers that
# need single args containing spaces should pass them via the image entry-
# point (-e VAR='spaced value' arrives intact because docker parses -e).
docker_run_argv=(docker run --rm)
if [[ -n "${INFINITO_RUN_FLAGS:-}" ]]; then
	# shellcheck disable=SC2206
	docker_run_argv+=(${INFINITO_RUN_FLAGS})
fi
docker_run_argv+=("${IMAGE}")
if [[ -n "${cmd:-}" ]]; then
	docker_run_argv+=(sh -lc "${cmd}")
fi

exec_flags=(-i)
if [[ -t 0 && -t 1 ]]; then
	exec_flags=(-it)
fi

exec docker exec "${exec_flags[@]}" "${INFINITO_CONTAINER}" "${docker_run_argv[@]}"
