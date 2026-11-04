#!/usr/bin/env bash
# CLI test for web-app-openclaw: the CLI inside the container reaches the
# gateway with the credential the container carries, and the agent reaches
# every MCP server it was configured against.
#
# Env (rendered into test.env from templates/test.env.j2):
#   MCP_TEST_ENABLED            whether this round configures MCP for OpenClaw at all
#   MCP_CLIENT_CONTAINER        addressable OpenClaw container
#   TRUSTED_PROXY_ENABLED       whether the gateway runs in trusted-proxy mode
#   GATEWAY_HOST, GATEWAY_PORT  published gateway port on this node
#   FORGED_USER                 allowlisted user a forged identity header claims
#   PROXY_SECRET_HEADER_PREFIX  prefix of the secret header name the front proxy sends
set -euo pipefail

: "${MCP_TEST_ENABLED:?}"
: "${MCP_CLIENT_CONTAINER:?}"
: "${TRUSTED_PROXY_ENABLED:?}"
: "${GATEWAY_HOST:?}"
: "${GATEWAY_PORT:?}"
: "${FORGED_USER:?}"
: "${PROXY_SECRET_HEADER_PREFIX:?}"

RETRIES=20
SLEEP_SECONDS=6

attempt=0
while :; do
    reached=0
    devices="$(container exec -i "${MCP_CLIENT_CONTAINER}" node dist/index.js devices list 2>&1)" || reached=$?
    if [[ ${reached} -eq 0 ]]; then
        echo "${devices}"
        break
    fi
    attempt=$((attempt + 1))
    if [[ ${attempt} -ge ${RETRIES} ]]; then
        echo "[FAIL] the CLI inside the container could not reach the gateway with OPENCLAW_GATEWAY_TOKEN or OPENCLAW_GATEWAY_PASSWORD: ${devices}" >&2
        exit 1
    fi
    sleep "${SLEEP_SECONDS}"
done

gateway="http://${GATEWAY_HOST}:${GATEWAY_PORT}"

forged_invoke() {
    curl -s --connect-timeout 5 --max-time 30 -o /dev/null -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' \
        -H "X-Forwarded-User: ${FORGED_USER}" \
        -H "X-Forwarded-Preferred-Username: ${FORGED_USER}" \
        -H 'X-Forwarded-Proto: https' \
        -H 'X-Forwarded-For: 203.0.113.7' \
        "$@" --data '{}' "${gateway}/tools/invoke"
}

refused() {
    local label="$1"
    shift
    local got
    got="$(forged_invoke "$@")"
    if [[ "${got}" != "401" ]]; then
        echo "[FAIL] a forged identity of ${FORGED_USER} ${label} must be refused with HTTP 401, got ${got}" >&2
        exit 1
    fi
    echo "[OK]   a forged identity ${label} is refused: HTTP ${got}"
}

if [[ "${TRUSTED_PROXY_ENABLED}" == "true" ]]; then
    reach="$(curl -s --connect-timeout 5 --max-time 30 -o /dev/null -w '%{http_code}' "${gateway}/healthz" || true)"
    if [[ "${reach}" != "200" ]]; then
        echo "[FAIL] the published gateway port must answer /healthz, got HTTP ${reach}" >&2
        exit 1
    fi
    refused "without the proxy secret header"
    refused "with a guessed proxy secret header" -H "${PROXY_SECRET_HEADER_PREFIX}-forged: 1"
fi

if [[ "${MCP_TEST_ENABLED}" != "true" ]]; then
    echo "SKIP: MCP is switched off in this round"
    echo "ALL CHECKS PASSED"
    exit 0
fi

attempt=0
while :; do
    reached=0
    out="$(container exec -i "${MCP_CLIENT_CONTAINER}" node dist/index.js mcp probe 2>&1)" || reached=$?
    if [[ ${reached} -eq 0 && -n "${out}" && "${out}" != *"failed to start server"* ]]; then
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
