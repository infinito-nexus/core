#!/usr/bin/env bash
# Settle the docker data-root filesystem for the deploy in progress and leave the
# decision in the calling shell's environment.
#
# Sourced rather than executed: resolve.sh hands its answer over a file in the
# GITHUB_ENV format, and the caller needs those values in its own environment,
# so the answer is routed through a temporary file of that format and sourced
# back.
#
# Nothing is drawn outside GitHub Actions, and nothing is drawn for the runner
# scope under act, which shares the developer's docker daemon: repointing its
# data root would take their local images with it. The node scope still draws
# under act, because those containers are the lab's own and are thrown away with
# it. A caller that gets no pick finds INFINITO_DOCKER_FILESYSTEM empty and
# leaves the data root where it is. Skipping therefore clears both keys rather
# than leaving them alone: they are declared in default.env, so a generated .env
# carries whatever was exported when it was made, and a caller gating its apply
# on the value would otherwise act on a stale pick - on the developer's own
# docker, in the very case the skip exists to protect.
#
# Reads:
#   INFINITO_DOCKER_FILESYSTEM_ALLOWED  space-separated subset of
#                                       'ext4 btrfs zfs' the run permits;
#                                       empty permits all three
#   INFINITO_DOCKER_FILESYSTEM_PICK     the kind the matrix assigned this row
#   INFINITO_DOCKER_FILESYSTEM_ENFORCED 'true' when a human named that kind, so
#                                       a host that cannot deliver it fails
#   INFINITO_DISTRO                     distro under test, recorded with the pick

# Param: $1 label the pick belongs to, e.g. compose/web-app-gitea/debian
# Param: $2 scope the pick gets applied in, runner or node
filesystem_pick() {
	local label="$1" scope="$2" answer resolver

	if [ -z "${GITHUB_ACTIONS:-}" ] ||
		{ [ -n "${ACT:-}" ] && [ "${scope}" = runner ]; }; then
		INFINITO_DOCKER_FILESYSTEM=""
		INFINITO_DOCKER_FILESYSTEM_REQUIRED=""
		export INFINITO_DOCKER_FILESYSTEM INFINITO_DOCKER_FILESYSTEM_REQUIRED
		echo "filesystem: no pick for the ${scope} here, leaving its data root alone"
		return 0
	fi

	resolver="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve.sh"
	answer="$(mktemp)"
	GITHUB_ENV="${answer}" bash "${resolver}" \
		"${INFINITO_DOCKER_FILESYSTEM_ALLOWED:-}" \
		"${label}" \
		"${INFINITO_DISTRO:-}" \
		"${scope}" \
		"${INFINITO_DOCKER_FILESYSTEM_ENFORCED:-}" \
		"${INFINITO_DOCKER_FILESYSTEM_PICK:-}"

	set -a
	# shellcheck source=/dev/null
	. "${answer}"
	set +a
	rm -f "${answer}"
}
