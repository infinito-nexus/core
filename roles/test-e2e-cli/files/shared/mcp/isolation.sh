#!/usr/bin/env bash
# Prove one role's MCP adapter sidecar is attached to exactly the networks it may.
#
# The attachment set is read from the engine, never by probing a peer's name: an
# unknown name does not fail to resolve in this environment, it falls through to
# a wildcard resolver that answers every name with one reachable address, so a
# name-based probe reports isolation broken for every provider.
#
# Swarm service introspection needs a manager. On a worker this reports that it
# cannot measure and returns success, because the manager in the same round does
# measure; a silent skip here would be indistinguishable from a pass.
#
# Env (rendered into test.env from test-e2e-cli/templates/mcp/test.env.j2):
#   MCP_SIDECAR_SERVICE     swarm service name, or compose container name
#   MCP_EXPECTED_NETWORKS   comma-separated networks the sidecar may hold
#   MCP_DEPLOYMENT_MODE     compose | swarm
set -euo pipefail

: "${MCP_SIDECAR_SERVICE:?}"
: "${MCP_EXPECTED_NETWORKS:?}"
: "${MCP_DEPLOYMENT_MODE:?}"

attached_swarm() {
    local id
    for id in $(container service inspect "${MCP_SIDECAR_SERVICE}" \
        --format '{{range .Endpoint.VirtualIPs}}{{.NetworkID}} {{end}}'); do
        container network inspect "${id}" --format '{{.Name}}'
    done
}

attached_compose() {
    container inspect --type container "${MCP_SIDECAR_SERVICE}" --format '{{json .NetworkSettings.Networks}}' |
        python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)))'
}

if [[ "${MCP_DEPLOYMENT_MODE}" == "swarm" ]]; then
    if ! container node ls >/dev/null 2>&1; then
        echo "SKIP: not a swarm manager, the manager of this round measures instead"
        exit 0
    fi
    attached="$(attached_swarm)"
else
    attached="$(attached_compose)"
fi

attached="$(printf '%s\n' "${attached}" | sed '/^$/d' | sort -u)"
expected="$(printf '%s' "${MCP_EXPECTED_NETWORKS}" | tr ',' '\n' | sed '/^$/d' | sort -u)"

echo "attached: $(printf '%s' "${attached}" | tr '\n' ' ')"

unexpected="$(comm -23 <(printf '%s\n' "${attached}") <(printf '%s\n' "${expected}"))"
absent="$(comm -13 <(printf '%s\n' "${attached}") <(printf '%s\n' "${expected}"))"

if [[ -n "${unexpected}" ]]; then
    echo "REJECTED the adapter is attached beyond its declared networks ($(printf '%s' "${unexpected}" | tr '\n' ' ')); a sidecar holding its provider's credential reaches that provider and its admitted clients only" >&2
fi

if [[ -n "${absent}" ]]; then
    echo "REJECTED the adapter is missing a declared attachment ($(printf '%s' "${absent}" | tr '\n' ' ')); an admitted client cannot reach it" >&2
fi

[[ -z "${unexpected}${absent}" ]] || exit 1
