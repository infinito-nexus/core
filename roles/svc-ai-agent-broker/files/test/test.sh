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
#   AGENT_KEY_ENV                 env var an agent carries its bearer key in
#   AGENT_MODEL                   model alias the broker configures agents with
#   AGENT_OPENCLAW_GROUP_PATH     Keycloak path of the openclaw agent-user group
#   AGENT_PLATFORMS_OFFERED       comma-separated platforms the broker serves
#   DEPLOYMENT_MODE               compose or swarm
#   IDLE_STOP, IDLE_MINUTES       lifecycle settings the broker must run with
#   MAX_RUNNING                   bound on concurrently running agents
#   USER_A_NAME, USER_A_EMAIL     first entitled user
#   USER_B_NAME, USER_B_EMAIL     second user, refused before being entitled
#   REQUEST_TIMEOUT               seconds a probe waits for its agent

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER_KEY="$(printf '%s' "${AGENT_BROKER_KEY_B64}" | base64 -d)"
OWNER_A="cli-isolation-a"
OWNER_B="cli-isolation-b"
FAILED=0

for required in hermes openclaw; do
	case ",${AGENT_PLATFORMS_OFFERED}," in
	*",${required},"*) ;;
	*)
		echo "[FAIL] ${required} is not offered by this deploy, which serves '${AGENT_PLATFORMS_OFFERED}'." >&2
		echo "       The broker withholds a platform whose context minimum '${AGENT_MODEL}' misses," >&2
		echo "       so point services.agent-broker.agents.model at a model that satisfies it." >&2
		exit 1
		;;
	esac
done

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

proxy_probe() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	container exec -i -e "SELF_NAME=${AGENT_BROKER_CONTAINER}" \
		"${AGENT_BROKER_CONTAINER}" python3 - <"${here}/proxy.py"
}

EMPTY_KEY_DIGEST="$(printf '' | sha256sum)"

agent_key_digest() {
	if [ "${DEPLOYMENT_MODE}" = "swarm" ]; then
		container docker service inspect -f '{{range .Spec.TaskTemplate.ContainerSpec.Env}}{{println .}}{{end}}' "$1" |
			sed -n "s/^${AGENT_KEY_ENV}=//p" | sha256sum
	else
		container docker inspect --type container -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" |
			sed -n "s/^${AGENT_KEY_ENV}=//p" | sha256sum
	fi
}

started_at() {
	container docker inspect --type container -f '{{.State.StartedAt}}' "$1"
}

broker_env() {
	container docker inspect --type container -f '{{range .Config.Env}}{{println .}}{{end}}' "${AGENT_BROKER_CONTAINER}" |
		sed -n "s/^$1=//p"
}

relayed() {
	container docker logs --since "$1" "${AGENT_BROKER_CONTAINER}" 2>&1 |
		grep -qF "\"event\": \"relay\", \"owner\": \"$2\", \"platform\": \"$3\", \"path\": \"/v1/chat/completions\", \"status\": 200"
}

# shellcheck disable=SC2329,SC2317 # reached through the EXIT trap below, which shellcheck does not follow.
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

proxy_output="$(proxy_probe)"
echo "${proxy_output}"
for expected in "exec 403" "binds 403" "mounts 403" "service_mounts 403" "delete 405"; do
	printf '%s\n' "${proxy_output}" | grep -qx "${expected}" ||
		fail "the socket proxy answered '$(printf '%s\n' "${proxy_output}" | grep "^${expected%% *} ")', expected '${expected}'"
done

for setting in IDLE_STOP:"${IDLE_STOP}" IDLE_MINUTES:"${IDLE_MINUTES}" MAX_RUNNING:"${MAX_RUNNING}" AGENT_MODEL:"${AGENT_MODEL}"; do
	[ "$(broker_env "${setting%%:*}")" = "${setting#*:}" ] ||
		fail "the broker runs with ${setting%%:*}=$(broker_env "${setting%%:*}"), not the inventory's ${setting#*:}"
done

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

for name in "${NAME_A}" "${NAME_B}"; do
	[ "$(agent_key_digest "${name}")" != "${EMPTY_KEY_DIGEST}" ] ||
		fail "${name} carries no ${AGENT_KEY_ENV}, so comparing the two keys proves nothing"
done

[ "$(agent_key_digest "${NAME_A}")" != "$(agent_key_digest "${NAME_B}")" ] ||
	fail "both owners' agents carry the same ${AGENT_KEY_ENV}"

if [ "${DEPLOYMENT_MODE}" = "swarm" ]; then
	container docker service inspect "${NAME_A}" "${NAME_B}" >/dev/null || fail "the two agent services are missing"
	tasks_before="$(container docker service ps -q "${NAME_A}")"
	output="$(probe "${BROKER_KEY}" "${OWNER_A}" "${USER_A_EMAIL}" hermes)"
	[ "$(status_of "${output}")" = "200" ] || fail "${USER_A_NAME}'s second prompt answered $(status_of "${output}"), not 200"
	[ "$(container docker service ps -q "${NAME_A}")" = "${tasks_before}" ] ||
		fail "the second prompt replaced the task of ${NAME_A} instead of reusing it"
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
if [ -z "${volume_a}" ] || [ "${volume_a}" = "${volume_b}" ]; then
	fail "the owners share a volume (${volume_a} / ${volume_b})"
fi

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

started_before="$(started_at "${NAME_A}")"
id_before="$(container docker inspect --type container -f '{{.Id}}' "${NAME_A}")"
output="$(probe "${BROKER_KEY}" "${OWNER_A}" "${USER_A_EMAIL}" hermes)"
[ "$(status_of "${output}")" = "200" ] || fail "${USER_A_NAME}'s second prompt answered $(status_of "${output}"), not 200"
[ "$(started_at "${NAME_A}")" = "${started_before}" ] ||
	fail "the second prompt restarted ${NAME_A} instead of reusing the running agent"

container docker stop "${NAME_A}" >/dev/null || fail "could not stop ${NAME_A} for the restart check"
output="$(probe "${BROKER_KEY}" "${OWNER_A}" "${USER_A_EMAIL}" hermes)"
[ "$(status_of "${output}")" = "200" ] || fail "the prompt after a stop answered $(status_of "${output}"), not 200"
[ "$(container docker inspect --type container -f '{{.Id}}' "${NAME_A}")" = "${id_before}" ] ||
	fail "the stopped agent was replaced instead of started again"
# nocheck: container-exec-resolver  agent container named by the broker
container exec "${NAME_A}" test -e "${AGENT_DATA_DIR}/cli-isolation-marker" ||
	fail "${NAME_A} lost its state across the stop"

[ "${FAILED}" -eq 0 ] && echo "[OK] two owners got two isolated agents under ${AGENT_RUNTIME}"
exit "${FAILED}"
