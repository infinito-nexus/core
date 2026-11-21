#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  the extracted production block, filled and replayed in place
#
# Env (test.env):
#   DOCS_TEST_COUNTRY     value for the <your-country> placeholder; a real
#                         country
#   DOCS_TEST_DNS         value for the <your-clearnet-resolver> placeholder
#   DOCS_TEST_DOMAIN      value for the <your-domain> placeholder; equal to
#                         INFINITO_DOMAIN
#   DOCS_TEST_ROLE        role whose page carries the instructions
#   DOCS_TEST_SRC_DIR     repository checkout on this host; its .env names the
#                         shared target's key and the path the target mounts the
#                         stack's checkout at for a host install
#   INFINITO_PULL_POLICY  never: build the image the block runs from
#                         DOCS_TEST_SRC_DIR on the stack daemon first

set -euo pipefail

BLOCK="${1:?}"
: "${DOCS_TEST_COUNTRY:?}"
: "${DOCS_TEST_DNS?}"
: "${DOCS_TEST_DOMAIN:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_SRC_DIR:?}"
: "${INFINITO_PULL_POLICY?}"

ENV_FILE="${DOCS_TEST_SRC_DIR}/.env"
CLAIM=/var/lib/infinito-target-claim
RECIPE_WORKDIR="${HOME}/.infinito.nexus"

if [ ! -r "${ENV_FILE}" ]; then
	echo "${ENV_FILE} is missing; run 'make dotenv' so the replay knows the shared target" >&2
	exit 1
fi
# shellcheck source=/dev/null
source <(grep -hE '^INFINITO_(DOMAIN|SRC_DIR|TARGET_KEY)=' "${ENV_FILE}")
: "${INFINITO_DOMAIN:?is missing from .env; run make dotenv}"
: "${INFINITO_SRC_DIR:?is missing from .env; run make dotenv}"
: "${INFINITO_TARGET_KEY:?is missing from .env; run make dotenv}"

if [ ! -r "${INFINITO_TARGET_KEY}.address" ]; then
	echo "${INFINITO_TARGET_KEY}.address is missing; no reset of the shared target handed this host a key, run 'make compose-target-reset'" >&2
	exit 1
fi
TARGET_IP="$(cat "${INFINITO_TARGET_KEY}.address")"

SSH_OPTIONS=(
	-i "${INFINITO_TARGET_KEY}"
	-o BatchMode=yes
	-o StrictHostKeyChecking=yes
	-o "UserKnownHostsFile=${INFINITO_TARGET_KEY}.known_hosts"
)

target() {
	# shellcheck disable=SC2029
	ssh "${SSH_OPTIONS[@]}" "root@${TARGET_IP}" "$@"
}

cleanup() {
	if [ "${RECIPE_WORKDIR_PREEXISTED}" = "0" ]; then
		rm -rf "${RECIPE_WORKDIR}"
	fi
	if [ "${#TRANSIENT_IMAGES[@]}" -gt 0 ]; then
		container image rm -f "${TRANSIENT_IMAGES[@]}" >/dev/null 2>&1
	fi
	return 0
}

claim_target() {
	if ! target true; then
		echo "the shared target at ${TARGET_IP} refuses ${INFINITO_TARGET_KEY} or its pinned host key; run 'make compose-target-reset'" >&2
		return 1
	fi
	if ! target mkdir "${CLAIM}"; then
		echo "the shared target was already used since its last reset, and replays take it one at a time; run 'make compose-target-reset'" >&2
		return 1
	fi
	return 0
}

fill_placeholders() {
	local public_key
	public_key="$(cat "${INFINITO_TARGET_KEY}.pub")"
	sed -i "s#<your-ssh-public-key>#${public_key}#g" "${BLOCK}"
	sed -i "s#<your-ssh-private-key-file>#${INFINITO_TARGET_KEY}#g" "${BLOCK}"
	sed -i "s#<your-domain>#${DOCS_TEST_DOMAIN}#g" "${BLOCK}"
	sed -i "s#<your-clearnet-resolver>#${DOCS_TEST_DNS}#g" "${BLOCK}"
	sed -i "s#<your-country>#${DOCS_TEST_COUNTRY}#g" "${BLOCK}"
}

report_failed_units() {
	local failed units unit
	failed="$(target systemctl list-units --no-pager --no-legend --plain --all \
		--state=failed,activating,auto-restart,deactivating)" || failed=""
	echo "=== units not running on the shared target ==="
	printf '%s\n' "${failed}"
	units="$(printf '%s\n' "${failed}" | awk '{print $1}')"
	for unit in ${units}; do
		echo "=== journalctl -xeu ${unit} ==="
		if ! target journalctl --no-pager -xeu "${unit}"; then
			echo "=== no journal for ${unit} ==="
		fi
	done
	return 0
}

guard_placeholders() {
	if grep -q '<your-' "${BLOCK}"; then
		echo "ERROR: the instructions carry a placeholder this test does not fill:" >&2
		grep -o '<your-[a-z-]*>' "${BLOCK}" | sort -u >&2
		return 1
	fi
	return 0
}

track_image() {
	[ -z "$1" ] || container image inspect "$1" >/dev/null 2>&1 || TRANSIENT_IMAGES+=("$1")
}

replay_image() {
	sed -nE '/^[[:space:]]*[^[:space:]]+ bash -c /{s#^[[:space:]]*([^[:space:]]+) bash -c .*#\1#p;q}' "${BLOCK}"
}

build_replay_image() {
	local image="$1" distro
	distro="$(sed -n 's/^INFINITO_DISTRO=//p' "${ENV_FILE}")"
	echo "=== Building ${image} on the stack daemon from ${DOCS_TEST_SRC_DIR} ==="
	(cd "${DOCS_TEST_SRC_DIR}" && INFINITO_DISTRO="${distro:?}" IMAGE_TAG="${image:?}" bash scripts/image/build.sh)
}

replay_over_ssh() {
	local image
	sed -i "s#^HOST=.*#HOST=${TARGET_IP}#" "${BLOCK}"
	guard_placeholders

	image="$(replay_image)"
	track_image "${image}"
	if [ "${INFINITO_PULL_POLICY}" = "never" ]; then
		build_replay_image "${image}"
	fi
	echo "=== Replay image: ${image} ==="
	echo "=== Replaying the instructions against ${TARGET_IP} ==="
	if ! (cd "$(dirname "${BLOCK}")" && bash -e "${BLOCK}"); then
		report_failed_units
		return 1
	fi
}

replay_in_target() {
	guard_placeholders

	if ! target test -f "${INFINITO_SRC_DIR}/Makefile"; then
		echo "the shared target carries no checkout at ${INFINITO_SRC_DIR}, so the host install has no tree to replay from" >&2
		return 1
	fi

	echo "=== Dropping the clone; ${INFINITO_SRC_DIR} is the tree under test ==="
	sed -i -E '/^git clone /d; /^cd core$/d' "${BLOCK}"

	echo "=== Replaying the instructions inside the shared target ==="
	if ! target "cd '${INFINITO_SRC_DIR}' && bash -e -s" <"${BLOCK}"; then
		report_failed_units
		return 1
	fi
}

if [ "${DOCS_TEST_DOMAIN}" != "${INFINITO_DOMAIN}" ]; then
	echo "the shared target answers ${INFINITO_DOMAIN} with itself, but this deploy's primary domain is ${DOCS_TEST_DOMAIN}" >&2
	exit 1
fi

if grep -qE '^docker run ' "${BLOCK}"; then
	REPLAY=replay_over_ssh
elif grep -qE '^git clone ' "${BLOCK}"; then
	REPLAY=replay_in_target
else
	echo "the ${DOCS_TEST_ROLE} block neither starts a container nor clones the repository, so this harness cannot tell whether it addresses a server or the machine it runs on" >&2
	exit 1
fi

if [ -e "${RECIPE_WORKDIR}" ]; then
	RECIPE_WORKDIR_PREEXISTED=1
else
	RECIPE_WORKDIR_PREEXISTED=0
fi
TRANSIENT_IMAGES=()
trap cleanup EXIT

echo "=== Target: the shared target at ${TARGET_IP} ==="
claim_target
fill_placeholders
"${REPLAY}"
