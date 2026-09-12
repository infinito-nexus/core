#!/usr/bin/env bash
# Drive the MCP contract checker for one role's endpoint.
#
# It runs in the provider's own network because the endpoint is `expose:`-only:
# the service name resolves there and nowhere else. Running it on the stack
# host would reach nothing.
#
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${MCP_TEST_NETWORK:?}"
: "${MCP_TEST_IMAGE:?}"
: "${MCP_URL:?}"
: "${MCP_TRANSPORT:?}"
: "${MCP_AUTH_HEADER:?}"
: "${MCP_EXPECTED_TOOLS:?}"
: "${MCP_UPSTREAM_SERVES:?}"
: "${MCP_READ_ARGUMENTS:?}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

container run --rm -i \
    --network "${MCP_TEST_NETWORK}" \
    -e "MCP_URL=${MCP_URL}" \
    -e "MCP_TRANSPORT=${MCP_TRANSPORT}" \
    -e "MCP_PATH_KEY=${MCP_PATH_KEY}" \
    -e "MCP_AUTH_HEADER=${MCP_AUTH_HEADER}" \
    -e "MCP_EXPECTED_TOOLS=${MCP_EXPECTED_TOOLS}" \
    -e "MCP_UPSTREAM_SERVES=${MCP_UPSTREAM_SERVES}" \
    -e "MCP_READ_TOOL=${MCP_READ_TOOL}" \
    -e "MCP_READ_ARGUMENTS=${MCP_READ_ARGUMENTS}" \
    -e "MCP_HOST_HEADER=${MCP_HOST_HEADER}" \
    "${MCP_TEST_IMAGE}" \
    python3 - <"${here}/contract.py"
