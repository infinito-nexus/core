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

	docker rm -f "${name}" >/dev/null 2>&1 || true # nocheck: shell-or-true -- cleanup of a possibly already-removed container
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

stamp() {
	local distro="$1"
	local line
	while IFS= read -r line; do
		printf '[%s][%(%H:%M:%S)T] %s\n' "${distro}" -1 "${line}"
	done
}

echo "🌐 Testing DNS on ${#distros[@]} distro(s) concurrently: ${distros[*]}"

declare -A pid
for d in "${distros[@]}"; do
	(
		set -o pipefail
		run_one "${d}" 2>&1 | stamp "${d}" | tee "/tmp/dns-${d}.log"
	) &
	pid["${d}"]=$!
done

rc_total=0
for d in "${distros[@]}"; do
	rc=0
	wait "${pid[${d}]}" || rc=$?
	if [[ "${rc}" -ne 0 ]]; then
		echo "❌ ${d} (exit ${rc})"
		echo "::error::DNS test failed for ${d}"
		rc_total=1
	else
		echo "✅ ${d}"
	fi
	docker rm -f "dns-dind-${d}" >/dev/null 2>&1 || true # nocheck: shell-or-true -- cleanup of a possibly already-removed container
done

exit "${rc_total}"
