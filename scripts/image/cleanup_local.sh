#!/usr/bin/env bash
# Remove the local toolchain images (<repo-name>/<distro>:<16 hex digits>, see
# scripts/meta/resolve/image/local.sh) that no registered worktree resolves and
# no container uses; every other image stays.
# A worktree without a .env is skipped: its local.sh would generate one inside it.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
cd "${repo_root}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

own_tag="$(bash scripts/meta/resolve/image/local.sh)"
repo_name="${own_tag%%/*}"

declare -A keep=()
while read -r key path; do
	[[ "${key}" == "worktree" && -f "${path}/scripts/meta/resolve/image/local.sh" && -f "${path}/.env" ]] || continue
	if resolved="$(cd "${path}" && env -i HOME="${HOME}" PATH="${PATH}" bash scripts/meta/resolve/image/local.sh 2>/dev/null)"; then
		keep["${resolved}"]="worktree ${path}"
	else
		echo "[build-cleanup] WARNING: ${path} resolves no tag; its image is kept only while a container uses it" >&2
	fi
done < <(git worktree list --porcelain)

while read -r image; do
	[[ -n "${image}" ]] && keep["${image}"]="container"
done < <(docker ps -a --format '{{.Image}}')

removed=0
while read -r image; do
	[[ "${image}" =~ ^${repo_name}/[a-z0-9._-]+:[0-9a-f]{16}$ ]] || continue
	if [[ -n "${keep[${image}]:-}" ]]; then
		echo "[build-cleanup] keep ${image} (${keep[${image}]})"
		continue
	fi
	echo "[build-cleanup] remove ${image}"
	if docker image rm "${image}"; then
		removed=$((removed + 1))
	else
		echo "[build-cleanup] WARNING: docker refused to remove ${image}" >&2
	fi
done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' --filter "reference=${repo_name}/*")

echo "[build-cleanup] removed ${removed} toolchain image(s)"
