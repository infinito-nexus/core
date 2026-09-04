#!/usr/bin/env bash
# Run the MCP test suite of whichever role staged this harness.
#
# A connection error is retried and a REJECTED verdict is not: the endpoint may
# still be warming up when the round reaches its tests, but a served surface
# that disagrees with the declared contract will disagree just as much in five
# minutes.
#
# Retrying is bounded by wall clock rather than by a count, because the budget
# it has to stay under is one: meta/tests.yml states the timeout the harness
# kills the run at, and both scale through the same lookup('timeout'). A
# retry count would keep its own budget and drift out from under that one.
#
# Env (rendered into test.env from test-e2e-cli/templates/mcp/test.env.j2):
#   MCP_TEST_ENABLED        whether this round serves MCP for the role at all
#   MCP_SIDECAR_SERVICE     the sidecar, empty for non-adapter providers
#   MCP_DEADLINE_SECONDS    when to stop retrying, below the harness timeout
set -euo pipefail

: "${MCP_TEST_ENABLED:?}"
: "${MCP_SIDECAR_SERVICE?}"
: "${MCP_DEADLINE_SECONDS:?}"

SLEEP_SECONDS=10

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${MCP_TEST_ENABLED}" in
    true) ;;
    false)
        echo "SKIP: MCP is switched off in this round"
        exit 0
        ;;
    *)
        echo "[FATAL] MCP_TEST_ENABLED is '${MCP_TEST_ENABLED}', neither true nor false" >&2
        exit 1
        ;;
esac

while :; do
    if out="$(bash "${here}/contract.sh" 2>&1)"; then
        echo "${out}"
        break
    fi
    if [[ "${out}" == *REJECTED* || ${SECONDS} -ge ${MCP_DEADLINE_SECONDS} ]]; then
        echo "${out}" >&2
        exit 1
    fi
    sleep "${SLEEP_SECONDS}"
done

if [[ -n "${MCP_SIDECAR_SERVICE}" ]]; then
    bash "${here}/isolation.sh"
fi

echo "ALL CHECKS PASSED"
