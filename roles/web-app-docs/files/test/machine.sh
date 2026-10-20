#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  the prepared production block
#
# Env (test.env):
#   DOCS_TEST_ROLE           role under replay, names the compose project
#   DOCS_TEST_SRC_DIR        repository checkout, holds the generated .env and
#                            carries the tree a host install replays from
#   DOCS_TEST_DOMAIN         domain the published block deploys, wildcarded onto
#                            the target for the length of the replay
#   DOCS_TEST_WORK           work directory, holds the replay key pair and the
#                            rendered Corefile
#   DOCS_TEST_REPLAY_PUBKEY  public half, authorized for root on the target

set -euo pipefail

BLOCK="${1:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_SRC_DIR:?}"
: "${DOCS_TEST_DOMAIN:?}"
: "${DOCS_TEST_WORK:?}"
: "${DOCS_TEST_REPLAY_PUBKEY:?}"

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PREFIX="docs-guide-"
PROJECT="${PROJECT_PREFIX}${DOCS_TEST_ROLE}"
SYSTEMD_TRIES=40
SYSTEMD_DELAY=3
SSH_TRIES=30
SSH_DELAY=2
RESOLVER_TRIES=30
RESOLVER_DELAY=2

machine() {
	docker compose --project-directory "${STAGE}" -p "${PROJECT}" "$@"
}

cleanup() {
	machine down -v --rmi local --remove-orphans >/dev/null 2>&1
	rm -f "${REPLAY_KEY}" "${REPLAY_KEY}.pub" "${COREFILE}"
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
		--format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' |
		awk '{print $1}'
}

resolver_upstream() {
	# shellcheck disable=SC2016
	machine exec -T machine \
		awk '$1 == "nameserver" && $2 !~ /^127\./ { printf "%s ", $2 }' /etc/resolv.conf
}

await_wildcard() {
	local address="$1" probe seen
	probe="docs-guide-probe.${DOCS_TEST_DOMAIN}"
	seen=""
	for _ in $(seq 1 "${RESOLVER_TRIES}"); do
		seen="$(machine exec -T machine getent hosts "${probe}" | awk '{print $1}')" || seen=""
		if [ "${seen}" = "${address}" ]; then
			return 0
		fi
		sleep "${RESOLVER_DELAY}"
	done
	echo "the ${DOCS_TEST_ROLE} target resolves ${probe} to '${seen}' instead of its own ${address}" >&2
	return 1
}

resolve_domain_to_target() {
	local address="$1" upstream
	upstream="$(resolver_upstream)"
	if [ -z "${upstream}" ]; then
		echo "the ${DOCS_TEST_ROLE} target carries no forwardable nameserver, so every name outside ${DOCS_TEST_DOMAIN} would stop resolving" >&2
		return 1
	fi

	echo "=== Answering *.${DOCS_TEST_DOMAIN} with the target's own ${address} ==="
	sed -e "s#\${DOCS_TEST_DOMAIN}#${DOCS_TEST_DOMAIN}#g" \
		-e "s#\${DOCS_TEST_TARGET_IP}#${address}#g" \
		-e "s#\${DOCS_TEST_UPSTREAM}#${upstream}#g" \
		"${STAGE}/Corefile.tmpl" >"${COREFILE}"

	machine up -d resolver
	printf 'nameserver %s\n' "${address}" | machine exec -T machine tee /etc/resolv.conf >/dev/null
	await_wildcard "${address}"
}

report_failed_units() {
	local failed units unit
	failed="$(machine exec -T machine systemctl list-units --no-pager --no-legend --plain --all \
		--state=failed,activating,auto-restart,deactivating)" || failed=""
	echo "=== units not running on the ${DOCS_TEST_ROLE} target ==="
	printf '%s\n' "${failed}"
	units="$(printf '%s\n' "${failed}" | awk '{print $1}')"
	for unit in ${units}; do
		echo "=== journalctl -xeu ${unit} ==="
		if ! machine exec -T machine journalctl --no-pager -xeu "${unit}"; then
			echo "=== no journal for ${unit} ==="
		fi
	done
	return 0
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

guard_placeholders() {
	if grep -q '<your-' "${BLOCK}"; then
		echo "ERROR: the instructions carry a placeholder this test does not fill:" >&2
		grep -o '<your-[a-z-]*>' "${BLOCK}" | sort -u >&2
		return 1
	fi
	return 0
}

replay_over_ssh() {
	echo "=== Giving the target an ssh server the published recipe can reach ==="
	machine exec -T -e DOCS_TEST_REPLAY_PUBKEY machine sh -s <"${STAGE}/sshd.sh"

	await_ssh "${TARGET_ADDRESS}"

	sed -i "s#^HOST=.*#HOST=${TARGET_ADDRESS}#" "${BLOCK}"
	guard_placeholders

	echo "=== Replay image: $(sed -nE 's#^[[:space:]]*([^[:space:]]+) bash -c .*#\1#p' "${BLOCK}" | head -1 || true) ==="
	echo "=== Replaying the instructions against ${TARGET_ADDRESS} ==="
	if ! (cd "${DOCS_TEST_WORK}" && bash -e "${BLOCK}"); then
		report_failed_units
		return 1
	fi
}

replay_in_target() {
	guard_placeholders

	if ! machine exec -T machine test -f "${DOCS_TEST_SRC_DIR}/Makefile"; then
		echo "the target carries no checkout at ${DOCS_TEST_SRC_DIR}, so the host install has no tree to replay from" >&2
		return 1
	fi

	echo "=== Dropping the clone; ${DOCS_TEST_SRC_DIR} is the tree under test ==="
	sed -i -E '/^git clone /d; /^cd core$/d' "${BLOCK}"

	echo "=== Replaying the instructions inside the target ==="
	if ! machine exec -T -w "${DOCS_TEST_SRC_DIR}" machine bash -e -s <"${BLOCK}"; then
		report_failed_units
		return 1
	fi
}

REPLAY_KEY="${DOCS_TEST_WORK}/docs-guide-${DOCS_TEST_ROLE}-key"
COREFILE="${DOCS_TEST_WORK}/Corefile"
RECIPE_WORKDIR="${HOME}/.infinito.nexus"
if [ -e "${RECIPE_WORKDIR}" ]; then
	RECIPE_WORKDIR_PREEXISTED=1
else
	RECIPE_WORKDIR_PREEXISTED=0
fi

if grep -qE '^docker run ' "${BLOCK}"; then
	REPLAY=replay_over_ssh
elif grep -qE '^git clone ' "${BLOCK}"; then
	REPLAY=replay_in_target
else
	echo "the ${DOCS_TEST_ROLE} block neither starts a container nor clones the repository, so this harness cannot tell whether it addresses a server or the machine it runs on" >&2
	exit 1
fi

MACHINE_BASE_IMAGE="$(base_image)"
export MACHINE_BASE_IMAGE

echo "=== Target: ${MACHINE_BASE_IMAGE} ==="
sweep_dead_machines
trap cleanup EXIT
machine up -d --build --pull always machine
await_systemd

TARGET_ADDRESS="$(target_address)"
if [ -z "${TARGET_ADDRESS}" ]; then
	echo "the ${DOCS_TEST_ROLE} target reported no bridge address" >&2
	exit 1
fi
resolve_domain_to_target "${TARGET_ADDRESS}"

"${REPLAY}"
