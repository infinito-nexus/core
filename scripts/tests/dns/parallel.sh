#!/usr/bin/env bash
#
# Args:
#   $@  distro ids (space-separated), e.g. "arch debian ubuntu".
#
# Inputs via env:
#   OWNER, REPO_NAME, GITHUB_SHA  image coordinates
#     -> ghcr.io/${OWNER}/${REPO_NAME}/${distro}:ci-${GITHUB_SHA}
#   GHCR_USER, GHCR_TOKEN         creds to pull the image from GHCR.

set -uo pipefail

: "${OWNER:?}" "${REPO_NAME:?}" "${GITHUB_SHA:?}"
read -r -a distros <<<"${*:-}"
: "${distros[0]:?no distros given}"

run_one() {
	local d="$1"
	local image="ghcr.io/${OWNER}/${REPO_NAME}/${d}:ci-${GITHUB_SHA}"
	local name="dns-dind-${d}"

	docker rm -f "${name}" >/dev/null 2>&1 || true
	docker run -d --name "${name}" \
		--privileged \
		--cgroupns=host \
		--security-opt seccomp=unconfined \
		--security-opt apparmor=unconfined \
		--tmpfs /run \
		--tmpfs /run/lock \
		-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
		-v /lib/modules:/lib/modules:ro \
		-e GITHUB_ACTIONS=true \
		-e GITHUB_REPOSITORY_OWNER="${OWNER}" \
		-e GITHUB_REPOSITORY="${OWNER}/${REPO_NAME}" \
		-e INFINITO_BUILD=0 \
		-e INFINITO_DISTRO="${d}" \
		-e INFINITO_IMAGE="${image}" \
		-e INFINITO_IMAGE_TAG="ci-${GITHUB_SHA}" \
		-e INFINITO_PULL_POLICY=always \
		-e GHCR_USER="${GHCR_USER:-}" \
		-e GHCR_TOKEN="${GHCR_TOKEN:-}" \
		"${image}" /sbin/init >/dev/null
	docker exec "${name}" bash -lc 'exec "${INFINITO_SRC_DIR}/scripts/tests/dns/inside.sh"'
}

declare -A pid
for d in "${distros[@]}"; do
	run_one "${d}" >"/tmp/dns-${d}.log" 2>&1 &
	pid["${d}"]=$!
done

rc_total=0
for d in "${distros[@]}"; do
	rc=0
	wait "${pid[${d}]}" || rc=$?
	echo "::group::DNS ${d} (exit ${rc})"
	cat "/tmp/dns-${d}.log"
	echo "::endgroup::"
	if [[ "${rc}" -ne 0 ]]; then
		echo "::error::DNS test failed for ${d}"
		rc_total=1
	fi
	docker rm -f "dns-dind-${d}" >/dev/null 2>&1 || true
done

exit "${rc_total}"
