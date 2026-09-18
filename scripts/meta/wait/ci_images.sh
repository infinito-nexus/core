#!/usr/bin/env bash
set -euo pipefail

# Env:
#   REGISTRY, OWNER, REPO_PREFIX, CI_TAG, INFINITO_DISTROS
#     image coordinates, as scripts/meta/resolve/missing/ci_images.sh reads them
#   WAIT_ATTEMPTS        polls before giving up (default 60)
#   WAIT_SLEEP_SECONDS   seconds between polls (default 10)

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolver="${script_dir}/../resolve/missing/ci_images.sh"

wait_attempts="${WAIT_ATTEMPTS:-60}"
wait_sleep_seconds="${WAIT_SLEEP_SECONDS:-10}"

echo "⏳ Waiting for the CI images tagged ${CI_TAG:?}"

for attempt in $(seq 1 "${wait_attempts}"); do
	if ! still_missing="$(bash "${resolver}")"; then
		echo "❌ Could not check the CI images; see the resolver's output above." >&2
		exit 2
	fi

	if [[ "${still_missing}" == "false" ]]; then
		echo "✅ Every CI image is available."
		exit 0
	fi

	echo "   attempt ${attempt}/${wait_attempts}: still incomplete"
	sleep "${wait_sleep_seconds}"
done

echo "❌ Gave up after ${wait_attempts} attempts." >&2
exit 1
