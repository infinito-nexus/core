#!/usr/bin/env bash
# Resolve the local Docker image tag for the current repository and distro.
# Output format: <repo-basename>/<distro>
# This is the SPOT for the local image name used by both build and compose.
set -euo pipefail

repo_name="$(bash "$(dirname "${BASH_SOURCE[0]}")/../repository/name.sh")"
# INFINITO_DISTRO is the single SPOT for distro selection (set by
# scripts/meta/env/defaults.sh). Read strictly here — no local fallback.
: "${INFINITO_DISTRO:?Source scripts/meta/env/defaults.sh or export INFINITO_DISTRO before invoking this script}"

printf '%s/%s\n' "${repo_name}" "${INFINITO_DISTRO}"
