#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  the prepared production block
#
# Env (test.env):
#   DOCS_TEST_ROLE           role under replay, names the compose project
#   DOCS_TEST_SRC_DIR        repository checkout, holds the generated .env
#   DOCS_TEST_WORK           work directory, holds the replay key pair
#   DOCS_TEST_REPLAY_PUBKEY  public half, authorized for root on the target

set -euo pipefail

BLOCK="${1:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_SRC_DIR:?}"
: "${DOCS_TEST_WORK:?}"
: "${DOCS_TEST_REPLAY_PUBKEY:?}"

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PREFIX="docs-guide-"
PROJECT="${PROJECT_PREFIX}${DOCS_TEST_ROLE}"
SYSTEMD_TRIES=40
SYSTEMD_DELAY=3
SSH_TRIES=30
SSH_DELAY=2

machine() {
	docker compose --project-directory "${STAGE}" -p "${PROJECT}" "$@"
}

cleanup() {
	machine down -v --rmi local --remove-orphans >/dev/null 2>&1
	rm -f "${REPLAY_KEY}" "${REPLAY_KEY}.pub"
	if [ "${RECIPE_WORKDIR_PREEXISTED}" = "0" ]; then
		rm -rf "${RECIPE_WORKDIR}"
	fi
	return 0
}

sweep_dead_machines() {
	container ps -aq --filter "name=^${PROJECT_PREFIX}" --filter status=exited |
		xargs -r container rm -f >/dev/null 2>&1
	return 0
}

base_image() {
	local env_file="${DOCS_TEST_SRC_DIR}/.env"
	if [ ! -r "${env_file}" ]; then
		echo "${env_file} is missing; run 'make dotenv' so the machine knows its base image" >&2
		return 1
	fi
	# shellcheck source=/dev/null
	source <(grep -h '^INFINITO_PARENT_IMAGE=' "${env_file}")
	printf '%s' "${INFINITO_PARENT_IMAGE:?}"
}

await_systemd() {
	local state=""
	for _ in $(seq 1 "${SYSTEMD_TRIES}"); do
		state="$(machine exec -T machine systemctl is-system-running 2>/dev/null || true)"
		case "${state}" in running | degraded) return 0 ;; esac
		sleep "${SYSTEMD_DELAY}"
	done
	echo "systemd never came up in the ${DOCS_TEST_ROLE} target (last: ${state:-unknown})" >&2
	return 1
}

target_address() {
	container inspect --type container "$(machine ps -q machine)" \
		--format '{{.NetworkSettings.IPAddress}}'
}

await_ssh() {
	local address="$1"
	for _ in $(seq 1 "${SSH_TRIES}"); do
		if ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
			-i "${REPLAY_KEY}" "root@${address}" true >/dev/null 2>&1; then
			return 0
		fi
		sleep "${SSH_DELAY}"
	done
	echo "sshd never answered on the ${DOCS_TEST_ROLE} target at ${address}" >&2
	return 1
}

REPLAY_KEY="${DOCS_TEST_WORK}/docs-guide-${DOCS_TEST_ROLE}-key"
RECIPE_WORKDIR="${HOME}/.infinito.nexus"
if [ -e "${RECIPE_WORKDIR}" ]; then
	RECIPE_WORKDIR_PREEXISTED=1
else
	RECIPE_WORKDIR_PREEXISTED=0
fi

if ! grep -qE '^docker run ' "${BLOCK}"; then
	echo "the ${DOCS_TEST_ROLE} block starts no container; this harness replays it on the stack host and would configure the host itself" >&2
	exit 1
fi

MACHINE_BASE_IMAGE="$(base_image)"
export MACHINE_BASE_IMAGE

echo "=== Target: ${MACHINE_BASE_IMAGE} ==="
sweep_dead_machines
trap cleanup EXIT
machine up -d --build --pull always
await_systemd

echo "=== Giving the target an ssh server the published recipe can reach ==="
machine exec -T -e DOCS_TEST_REPLAY_PUBKEY machine sh -s <"${STAGE}/sshd.sh"

TARGET_ADDRESS="$(target_address)"
if [ -z "${TARGET_ADDRESS}" ]; then
	echo "the ${DOCS_TEST_ROLE} target reported no bridge address" >&2
	exit 1
fi
await_ssh "${TARGET_ADDRESS}"

sed -i "s#^HOST=.*#HOST=${TARGET_ADDRESS}#" "${BLOCK}"

if grep -q '<your-' "${BLOCK}"; then
	echo "ERROR: the instructions carry a placeholder this test does not fill:" >&2
	grep -o '<your-[a-z-]*>' "${BLOCK}" | sort -u >&2
	exit 1
fi

echo "=== Replay image: $(sed -nE 's#^[[:space:]]*([^[:space:]]+) bash -c .*#\1#p' "${BLOCK}" | head -1 || true) ==="
echo "=== Replaying the instructions against ${TARGET_ADDRESS} ==="
(cd "${DOCS_TEST_WORK}" && bash -e "${BLOCK}")
