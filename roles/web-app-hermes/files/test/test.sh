#!/usr/bin/env bash
# CLI test for web-app-hermes: the agent reaches every MCP server it was
# configured against, and each one answers with a tool list.
#
# Env (rendered into test.env from templates/test.env.j2):
#   MCP_TEST_ENABLED      whether this round configures MCP for Hermes at all
#   MCP_CLIENT_CONTAINER  addressable Hermes container
#   MCP_SERVER_IDS        JSON array of the discovered server ids
set -euo pipefail

: "${MCP_TEST_ENABLED:?}"
: "${MCP_CLIENT_CONTAINER:?}"
: "${MCP_SERVER_IDS:?}"

RETRIES=20
SLEEP_SECONDS=6

if [[ "${MCP_TEST_ENABLED}" != "true" ]]; then
    echo "SKIP: MCP is switched off in this round"
    exit 0
fi

mapfile -t servers < <(printf '%s' "${MCP_SERVER_IDS}" |
    python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)))')

if [[ ${#servers[@]} -eq 0 ]]; then
    echo "[FATAL] MCP is on but no server was discovered; a client with an" \
        "empty server list is indistinguishable from one that lost its" \
        "providers" >&2
    exit 1
fi

failed=0
for id in "${servers[@]}"; do
    attempt=0
    while :; do
        out="$(container exec -i "${MCP_CLIENT_CONTAINER}" hermes mcp test "${id//-/_}" 2>&1 || true)"
        if [[ "${out}" == *"Tools discovered:"* && "${out}" != *"Connection failed"* ]]; then
            echo "[OK] ${id}"
            break
        fi
        attempt=$((attempt + 1))
        if [[ ${attempt} -ge ${RETRIES} ]]; then
            echo "[FAIL] ${id}: ${out}" >&2
            failed=1
            break
        fi
        sleep "${SLEEP_SECONDS}"
    done
done

[[ ${failed} -eq 0 ]] || exit 1

echo "ALL CHECKS PASSED"
