#!/usr/bin/env bash
# Resolve the local Docker image tag for the current repository and distro.
# Output format: <repo-name>/<distro>:<hash>
#   <repo-name> names the primary checkout, so it is the same in every worktree.
#   <hash> digests the toolchain stage's inputs, build arguments and parent
#   image ID (utils/docker/image/toolchain.py); an absent parent hashes as empty.
# This is the SPOT for the local image name used by both build and compose.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${repo_root}/scripts/meta/env/load.sh"
: "${INFINITO_DISTRO:?Source scripts/meta/env/load.sh or export INFINITO_DISTRO before invoking this script}"
: "${INFINITO_PARENT_IMAGE:?Source scripts/meta/env/load.sh or export INFINITO_PARENT_IMAGE before invoking this script}"

if ! name_root="$(cd "${repo_root}" && bash "${script_dir}/../repository/primary.sh" 2>/dev/null)" || [[ ! -d "${name_root}" ]]; then
	name_root="${repo_root}"
fi
repo_name="$(cd "${name_root}" && bash "${script_dir}/../repository/name.sh")"

if ! parent_id="$(docker image inspect --format '{{.Id}}' "${INFINITO_PARENT_IMAGE}" 2>/dev/null)"; then
	parent_id=""
fi
input_hash="$(cd "${repo_root}" && PYTHONPATH="${repo_root}" "${PYTHON}" -m utils.docker.image.toolchain hash --parent-id "${parent_id}")"

printf '%s/%s:%s\n' "${repo_name}" "${INFINITO_DISTRO}" "${input_hash}"
