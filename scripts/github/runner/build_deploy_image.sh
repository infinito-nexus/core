#!/usr/bin/env bash
# Env:
#   GITHUB_ENV           env file of the job's later steps (required)
#   MAX_ATTEMPTS         attempts to pull INFINITO_PARENT_IMAGE (pull_with_retry.sh)
#   RETRY_DELAY_SECONDS  seconds between those attempts (pull_with_retry.sh)
# Output (appended to GITHUB_ENV):
#   INFINITO_IMAGE        the image just built from this checkout, named by
#                         scripts/meta/resolve/image/local.sh
#   INFINITO_PULL_POLICY  never, so the deploy starts that local image
set -euo pipefail

: "${GITHUB_ENV:?Missing GITHUB_ENV}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"
cd "${repo_root}"

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

# Exception: local.sh hashes the parent image ID, an absent one as empty; pull
# it first, or make build-missing and the name read below disagree.
bash scripts/github/runner/pull_with_retry.sh "${INFINITO_PARENT_IMAGE:?Missing INFINITO_PARENT_IMAGE}"
make build-missing

image="$(bash scripts/meta/resolve/image/local.sh)"
docker image inspect --format '{{.Id}}' "${image}" >/dev/null

{
	echo "INFINITO_IMAGE=${image}"
	echo "INFINITO_PULL_POLICY=never"
} >>"${GITHUB_ENV}"
echo "Deploy pinned to ${image}, built from this checkout."
