#!/usr/bin/env bash
# Resolve the pull ref of a service declared in a role's meta/services.yml.
# Usage: service_ref.sh <role> <service> <upstream|mirror>
#   upstream  the declared upstream ref; never touches the network
#   mirror    the GHCR mirror ref when that tag exists, otherwise the upstream ref
# Output format: <image>:<version>
# This is the SPOT for image refs consumed outside Ansible (CI workflows, helper scripts).
set -euo pipefail

usage="Usage: service_ref.sh <role> <service> <upstream|mirror>"
role="${1:?${usage}}"
service="${2:?${usage}}"
source_kind="${3:?${usage}}"

case "${source_kind}" in
upstream | mirror) ;;
*)
	echo "Unknown source '${source_kind}'. ${usage}" >&2
	exit 2
	;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../../.." && pwd)"
services_yml="${repo_root}/roles/${role}/meta/services.yml"

if [[ ! -f "${services_yml}" ]]; then
	echo "No such services file: ${services_yml}" >&2
	exit 1
fi

if ! pair="$(awk -v want="${service}" '
	/^[^[:space:]#]/ { in_block = ($0 == want ":") }
	in_block && $1 == "image:"   { image = $2 }
	in_block && $1 == "version:" { version = $2 }
	END {
		gsub(/"/, "", version)
		if (image == "" || version == "") exit 1
		printf "%s %s\n", image, version
	}
' "${services_yml}")"; then
	echo "No image/version pair for service '${service}' in ${services_yml}" >&2
	exit 1
fi

read -r image version <<<"${pair}"
upstream="${image}:${version}"

if [[ "${source_kind}" == upstream ]]; then
	printf '%s\n' "${upstream}"
	exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
	echo "docker is unavailable; using upstream ${upstream}" >&2
	printf '%s\n' "${upstream}"
	exit 0
fi

if ! namespace="$("${repo_root}/scripts/meta/resolve/repository/owner.sh")" ||
	! repository="$("${repo_root}/scripts/meta/resolve/repository/name.sh")"; then
	echo "Could not resolve the GHCR namespace/repository; using upstream ${upstream}" >&2
	printf '%s\n' "${upstream}"
	exit 0
fi

if [[ -z "${INFINITO_GHCR_MIRROR_PREFIX:-}" ]]; then
	INFINITO_GHCR_MIRROR_PREFIX="$(awk -F= '$1 == "INFINITO_GHCR_MIRROR_PREFIX" { print $2; exit }' "${repo_root}/default.env")"
fi
: "${INFINITO_GHCR_MIRROR_PREFIX:?not in the environment and not declared in default.env}"

first="${image%%/*}"
case "${first}" in
docker.io | registry-1.docker.io | index.docker.io)
	registry="docker.io"
	name="${image#*/}"
	;;
*.* | *:*)
	registry="${first}"
	name="${image#*/}"
	;;
*)
	registry="docker.io"
	name="${image}"
	;;
esac

mirror="ghcr.io/${namespace}/${repository}/${INFINITO_GHCR_MIRROR_PREFIX}/${registry}/${name}:${version}"

if docker manifest inspect "${mirror}" >/dev/null 2>&1; then
	echo "Resolved ${upstream} to GHCR mirror ${mirror}" >&2
	printf '%s\n' "${mirror}"
else
	echo "No GHCR mirror for ${upstream} yet; using upstream" >&2
	printf '%s\n' "${upstream}"
fi
