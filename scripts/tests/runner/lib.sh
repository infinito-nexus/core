#!/usr/bin/env bash
# shellcheck shell=bash
#
# Sourced. The shared test runner infinito-test-<hash>: one long-lived container
# per toolchain image (scripts/meta/resolve/image/local.sh), started on first
# use, mounting every worktree root at its host path.
# Param INFINITO_WORKTREE_ROOTS: colon-separated roots the runner mounts; empty
#   mounts the primary checkout and ${HOME}/.local/share/worktrees.
# Param infinito_test_runner_exec <checkout> [docker exec options] -- <command>:
#   runs <command> in the runner with <checkout> as working directory and
#   INFINITO_SRC_DIR, and a TMPDIR of its own; refuses a checkout outside the
#   mounted roots.

_infinito_test_runner_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
_infinito_test_runner_down_target="make test-runner-down"
_infinito_test_runner_roots_label="nexus.infinito.worktree-roots"
# Exception: INFINITO_SRC_DIR is a build argument of the image tag, captured here
# because the wrappers point it at the invoking checkout before they exec.
_infinito_test_runner_image_src_dir="${INFINITO_SRC_DIR:-}"

infinito_test_runner_image() {
	INFINITO_SRC_DIR="${_infinito_test_runner_image_src_dir}" \
		bash "${_infinito_test_runner_repo}/scripts/meta/resolve/image/local.sh"
}

infinito_test_runner_name() {
	printf 'infinito-test-%s\n' "${1##*:}"
}

infinito_test_runner_roots() {
	local root
	if [[ -n "${INFINITO_WORKTREE_ROOTS:-}" ]]; then
		tr ':' '\n' <<<"${INFINITO_WORKTREE_ROOTS}"
	else
		(cd "${_infinito_test_runner_repo}" && bash scripts/meta/resolve/repository/primary.sh)
		printf '%s\n' "${HOME}/.local/share/worktrees"
	fi | while IFS= read -r root; do
		if [[ -n "${root}" && -d "${root}" ]]; then
			printf '%s\n' "${root%/}"
		fi
	done
}

infinito_test_runner_network() {
	(cd "${_infinito_test_runner_repo}" && "${PYTHON:?source scripts/meta/env/load.sh}" -m cli.administration.infra attach)
}

infinito_test_runner_up() {
	local image="$1" name="$2" root roots="" lockfd network
	local -a mounts=() networks=()
	exec {lockfd}>"/tmp/${name}.lock"
	flock "${lockfd}"
	case "$(docker inspect --format '{{.State.Running}}' "${name}" 2>/dev/null)" in
	true) ;;
	false) docker start "${name}" >/dev/null ;;
	*)
		INFINITO_SRC_DIR="${_infinito_test_runner_image_src_dir}" IMAGE_TAG="${image}" \
			bash "${_infinito_test_runner_repo}/scripts/image/build.sh" --missing >&2
		while IFS= read -r root; do
			mounts+=(-v "${root}:${root}")
			roots="${roots:+${roots}:}${root}"
		done < <(infinito_test_runner_roots)
		network="$(infinito_test_runner_network)"
		if [[ -n "${network}" ]]; then
			networks=(--network "${network}")
		fi
		echo ">>> Starting the shared test runner ${name} from ${image}" >&2
		docker run -d --name "${name}" --privileged --cgroupns=host --no-healthcheck \
			--tmpfs /run --tmpfs /run/lock \
			-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
			-v "${INFINITO_DOCKER_MOUNT:?source scripts/meta/env/load.sh}" \
			-e INFINITO_DOTENV_HOST_OWNED=true \
			--label "${_infinito_test_runner_roots_label}=${roots}" \
			"${networks[@]}" "${mounts[@]}" "${image}" /sbin/init >/dev/null
		if ! docker exec "${name}" timeout "${INFINITO_WAIT_HEALTH_TIMEOUT_S:?source scripts/meta/env/load.sh}" \
			systemctl is-system-running --wait >/dev/null 2>&1; then
			echo ">>> ${name}: systemd booted degraded or not within INFINITO_WAIT_HEALTH_TIMEOUT_S" >&2
		fi
		;;
	esac
	exec {lockfd}>&-
}

infinito_test_runner_exec() {
	local checkout="$1" image name root roots="" inside="" tmpdir
	local -a options=()
	shift
	while [[ $# -gt 0 && "$1" != "--" ]]; do
		options+=("$1")
		shift
	done
	shift
	image="$(infinito_test_runner_image)"
	name="$(infinito_test_runner_name "${image}")"
	while IFS= read -r root; do
		[[ -n "${root}" ]] || continue
		roots="${roots:+${roots} }${root}"
		if [[ "${checkout}" == "${root}" || "${checkout}" == "${root%/}/"* ]]; then
			inside="${root}"
		fi
	done < <(
		if docker inspect "${name}" >/dev/null 2>&1; then
			docker inspect --format "{{index .Config.Labels \"${_infinito_test_runner_roots_label}\"}}" "${name}" | tr ':' '\n'
		else
			infinito_test_runner_roots
		fi
	)
	if [[ -z "${inside}" ]]; then
		echo "Checkout ${checkout} is outside the worktree roots of ${name} (${roots}). Add its root to INFINITO_WORKTREE_ROOTS, run '${_infinito_test_runner_down_target}', and the next test call recreates the runner." >&2
		return 2
	fi
	infinito_test_runner_up "${image}" "${name}"
	tmpdir="/tmp/infinito-test/$(printf '%s' "${checkout}" | sha256sum | cut -c1-16)"
	docker exec "${name}" mkdir -p "${tmpdir}"
	docker exec --workdir "${checkout}" \
		-e INFINITO_SRC_DIR="${checkout}" \
		-e TMPDIR="${tmpdir}" \
		"${options[@]}" \
		"${name}" "$@"
}
