#!/usr/bin/env bash
# CLI test for web-app-openclaw: the agent reaches every MCP server it was
# configured against.
#
# Env (rendered into test.env from templates/test.env.j2):
#   MCP_TEST_ENABLED      whether this round configures MCP for OpenClaw at all
#   MCP_CLIENT_CONTAINER  addressable OpenClaw container
set -euo pipefail

: "${MCP_TEST_ENABLED:?}"
: "${MCP_CLIENT_CONTAINER:?}"

RETRIES=20
SLEEP_SECONDS=6

if [[ "${MCP_TEST_ENABLED}" != "true" ]]; then
    echo "SKIP: MCP is switched off in this round"
    exit 0
fi

attempt=0
while :; do
    out="$(container exec -i "${MCP_CLIENT_CONTAINER}" node dist/index.js mcp probe 2>&1 || true)"
    if [[ -n "${out}" && "${out}" != *"failed to start server"* ]]; then
        echo "${out}"
        echo "ALL CHECKS PASSED"
        exit 0
    fi
    attempt=$((attempt + 1))
    if [[ ${attempt} -ge ${RETRIES} ]]; then
        echo "[FAIL] OpenClaw could not connect to a configured MCP server: ${out}" >&2
        exit 1
    fi
    sleep "${SLEEP_SECONDS}"
done
