#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (rendered into test.env from templates/test.env.j2):
#   AGENT_BROKER_CONTAINER        resolved broker container (CLI_LOCAL_CID)
#   AGENT_BROKER_PORT             broker port inside the container
#   AGENT_BROKER_KEY_B64          base64 broker key
#   AGENT_RUNTIME                 runtime every agent must run under
#   AGENT_DATA_DIR                state mount of a hermes agent
#   AGENT_PORT                    API port of a hermes agent
#   AGENT_GROUP_PATH              Keycloak path of the hermes agent-user group
#   AGENT_OPENCLAW_GROUP_PATH     Keycloak path of the openclaw agent-user group
#   DEPLOYMENT_MODE               compose or swarm
#   USER_A_NAME, USER_A_EMAIL     first entitled user
#   USER_B_NAME, USER_B_EMAIL     second user, refused before being entitled
#   REQUEST_TIMEOUT               seconds a probe waits for its agent

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER_KEY="$(printf '%s' "${AGENT_BROKER_KEY_B64}" | base64 -d)"
OWNER_A="cli-isolation-a"
OWNER_B="cli-isolation-b"
FAILED=0

fail() {
	echo "[FAIL] $*" >&2
	FAILED=1
}

agent_name() {
	printf 'agent-%s-%s' "$1" "$(printf '%s' "$2" | sha256sum | cut -c1-16)"
}

kc_membership() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	container exec -i \
		-e "MEMBER=$1" \
		-e "METHOD=$2" \
		-e "GROUP_PATH=$3" \
		"${AGENT_BROKER_CONTAINER}" python3 - <"${here}/membership.py"
}

probe() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	container exec -i \
		-e "PORT=${AGENT_BROKER_PORT}" \
		-e "KEY=$1" \
		-e "OWNER=$2" \
		-e "EMAIL=$3" \
		-e "MODEL=$4" \
		-e "TIMEOUT=${REQUEST_TIMEOUT}" \
		"${AGENT_BROKER_CONTAINER}" python3 - <"${here}/probe.py"
}

status_of() {
	printf '%s\n' "$1" | sed -n 's/^STATUS //p'
}

relayed() {
	container docker logs --since "$1" "${AGENT_BROKER_CONTAINER}" 2>&1 |
		grep -qF "\"event\": \"relay\", \"owner\": \"$2\", \"platform\": \"$3\", \"path\": \"/v1/chat/completions\", \"status\": 200"
}

cleanup() {
	kc_membership "${USER_A_NAME}" DELETE "${AGENT_GROUP_PATH}"
	kc_membership "${USER_B_NAME}" DELETE "${AGENT_GROUP_PATH}"
	kc_membership "${USER_A_NAME}" DELETE "${AGENT_OPENCLAW_GROUP_PATH}"
	local name
	for name in "${NAME_A}" "${NAME_B}" "${NAME_CLAW}"; do
		if [ "${DEPLOYMENT_MODE}" = "swarm" ]; then
			container docker service rm "${name}" >/dev/null 2>&1
		else
			container docker rm -f "${name}" >/dev/null 2>&1
		fi
		container docker network disconnect -f "${name}" "${AGENT_BROKER_CONTAINER}" >/dev/null 2>&1
		container docker network rm "${name}" >/dev/null 2>&1
		container docker volume rm "${name}" >/dev/null 2>&1
	done
}

NAME_A="$(agent_name hermes "${OWNER_A}")"
NAME_B="$(agent_name hermes "${OWNER_B}")"
NAME_CLAW="$(agent_name openclaw "${OWNER_A}")"
trap cleanup EXIT

output="$(probe "" "${OWNER_A}" "${USER_A_EMAIL}" hermes)"
[ "$(status_of "${output}")" = "401" ] || fail "a request without the broker key answered $(status_of "${output}"), not 401"

kc_membership "${USER_B_NAME}" DELETE "${AGENT_GROUP_PATH}"
output="$(probe "${BROKER_KEY}" "${OWNER_B}" "${USER_B_EMAIL}" hermes)"
[ "$(status_of "${output}")" = "403" ] || fail "${USER_B_NAME} outside the group answered $(status_of "${output}"), not 403"
if container docker inspect --type container "${NAME_B}" >/dev/null 2>&1 ||
	container docker service inspect "${NAME_B}" >/dev/null 2>&1; then
	fail "the refused request still created ${NAME_B}"
fi

kc_membership "${USER_A_NAME}" PUT "${AGENT_GROUP_PATH}" || fail "could not grant ${USER_A_NAME} ${AGENT_GROUP_PATH}"
kc_membership "${USER_B_NAME}" PUT "${AGENT_GROUP_PATH}" || fail "could not grant ${USER_B_NAME} ${AGENT_GROUP_PATH}"
kc_membership "${USER_A_NAME}" PUT "${AGENT_OPENCLAW_GROUP_PATH}" || fail "could not grant ${USER_A_NAME} ${AGENT_OPENCLAW_GROUP_PATH}"
sleep 65

since="$(date +%s)"
output="$(probe "${BROKER_KEY}" "${OWNER_A}" "${USER_A_EMAIL}" hermes)"
echo "${output}"
[ "$(status_of "${output}")" = "200" ] || fail "${USER_A_NAME}'s agent answered $(status_of "${output}"), not 200"
relayed "${since}" "${OWNER_A}" hermes || fail "${USER_A_NAME}'s hermes agent never got a model answer through the relay"
output="$(probe "${BROKER_KEY}" "${OWNER_B}" "${USER_B_EMAIL}" hermes)"
echo "${output}"
[ "$(status_of "${output}")" = "200" ] || fail "${USER_B_NAME}'s agent answered $(status_of "${output}"), not 200"
relayed "${since}" "${OWNER_B}" hermes || fail "${USER_B_NAME}'s hermes agent never got a model answer through the relay"
output="$(probe "${BROKER_KEY}" "${OWNER_A}" "${USER_A_EMAIL}" openclaw)"
echo "${output}"
[ "$(status_of "${output}")" = "200" ] || fail "${USER_A_NAME}'s openclaw agent answered $(status_of "${output}"), not 200"
relayed "${since}" "${OWNER_A}" openclaw || fail "${USER_A_NAME}'s openclaw agent never got a model answer through the relay"

if [ "${DEPLOYMENT_MODE}" = "swarm" ]; then
	container docker service inspect "${NAME_A}" "${NAME_B}" >/dev/null || fail "the two agent services are missing"
	exit "${FAILED}"
fi

for name in "${NAME_A}" "${NAME_B}"; do
	runtime="$(container docker inspect --type container -f '{{.HostConfig.Runtime}}' "${name}")"
	[ "${runtime}" = "${AGENT_RUNTIME}" ] || fail "${name} runs under '${runtime}', not '${AGENT_RUNTIME}'"
done

[ "$(container docker inspect --type container -f '{{.Id}}' "${NAME_A}")" != "$(container docker inspect --type container -f '{{.Id}}' "${NAME_B}")" ] ||
	fail "both owners share one container"
volume_a="$(container docker inspect --type container -f '{{range .Mounts}}{{.Name}}{{end}}' "${NAME_A}")"
volume_b="$(container docker inspect --type container -f '{{range .Mounts}}{{.Name}}{{end}}' "${NAME_B}")"
[ -n "${volume_a}" ] && [ "${volume_a}" != "${volume_b}" ] || fail "the owners share a volume (${volume_a} / ${volume_b})"

# nocheck: container-exec-resolver  agent container named by the broker
container exec "${NAME_A}" sh -c "echo isolated > '${AGENT_DATA_DIR}/cli-isolation-marker'" || fail "could not write the marker in ${NAME_A}"
# nocheck: container-exec-resolver  agent container named by the broker
if container exec "${NAME_B}" test -e "${AGENT_DATA_DIR}/cli-isolation-marker"; then
	fail "${NAME_B} sees the file ${NAME_A} wrote"
fi

ip_b="$(container docker inspect --type container -f "{{(index .NetworkSettings.Networks \"${NAME_B}\").IPAddress}}" "${NAME_B}")"
[ -n "${ip_b}" ] || fail "${NAME_B} has no address on its own network"
# nocheck: container-exec-resolver  agent container named by the broker
if container exec "${NAME_A}" python3 -c "import socket; socket.create_connection(('${ip_b}', ${AGENT_PORT}), 3)" 2>/dev/null; then
	fail "${NAME_A} reached ${NAME_B} at ${ip_b}:${AGENT_PORT}"
fi

[ "${FAILED}" -eq 0 ] && echo "[OK] two owners got two isolated agents under ${AGENT_RUNTIME}"
exit "${FAILED}"
