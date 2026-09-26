#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  the prepared production block
#
# Env (test.env):
#   DOCS_TEST_ROLE       role under replay, names the compose project
#   DOCS_TEST_SRC_DIR    repository checkout, mounted into the machine

set -euo pipefail

BLOCK="${1:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_SRC_DIR:?}"

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="docs-guide-${DOCS_TEST_ROLE}"
PREPARE="scripts/tests/workspace/base/01_install.sh"
SYSTEMD_TRIES=40
SYSTEMD_DELAY=3

export DOCS_TEST_WORK="${STAGE}/work"
mkdir -p "${DOCS_TEST_WORK}"

machine() {
	docker compose --project-directory "${STAGE}" -p "${PROJECT}" "$@"
}

in_machine() {
	machine exec -T -w "${DOCS_TEST_SRC_DIR}" machine "$@"
}

cleanup() {
	machine down -v --rmi local --remove-orphans >/dev/null 2>&1
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
	echo "systemd never came up in the ${DOCS_TEST_ROLE} machine (last: ${state:-unknown})" >&2
	return 1
}

if grep -q '^git clone ' "${BLOCK}"; then
	echo "=== Dropping the clone; ${DOCS_TEST_SRC_DIR} is the tree under test ==="
	sed -i -E '/^git clone /d; /^cd core$/d' "${BLOCK}"
	workdir="${DOCS_TEST_SRC_DIR}"
else
	workdir="${DOCS_TEST_WORK}"
fi

MACHINE_BASE_IMAGE="$(base_image)"
export MACHINE_BASE_IMAGE

echo "=== Machine: ${MACHINE_BASE_IMAGE} ==="
trap cleanup EXIT
machine up -d --build --pull always
await_systemd

echo "=== Preparing it for Infinito.Nexus (${PREPARE}) ==="
in_machine bash "${PREPARE}"

echo "=== Replaying the instructions in that machine ==="
machine exec -T -w "${workdir}" machine bash -s <"${BLOCK}"
