#!/usr/bin/env bash
# Resolve the prebuilt CI environment image for the current distro.
#
# Param:
#   INFINITO_DISTRO             distro to resolve for
#   INFINITO_IMAGE_TAG          tag the CI images were pushed under
#   INFINITO_IMAGE_REPOSITORY   repository name; resolve/repository/name.sh falls back to git metadata when empty
#
# Output: the image reference, or nothing when no registry owner is in scope,
# which is the caller's signal to build the image locally instead.
#
# act sets the GITHUB_REPOSITORY* vars to placeholders (nektos/act), so the
# owner guard below passes and the resolved path 403s on ghcr.io.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${ACT:-}" == "true" ]]; then
	exit 0
fi

if [[ -z "${OWNER:-}" && -z "${GITHUB_REPOSITORY_OWNER:-}" && -z "${GITHUB_REPOSITORY:-}" ]]; then
	exit 0
fi

: "${INFINITO_DISTRO:?INFINITO_DISTRO is required}"
: "${INFINITO_IMAGE_TAG:?INFINITO_IMAGE_TAG is required}"

python3 -m cli.meta.ci.image_ref --kind environment \
	--distro "${INFINITO_DISTRO}" \
	--owner "$(scripts/meta/resolve/repository/owner.sh)" \
	--repository "$(scripts/meta/resolve/repository/name.sh)" \
	--tag "${INFINITO_IMAGE_TAG}"
