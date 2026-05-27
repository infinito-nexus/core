#!/usr/bin/env bash
set -euo pipefail

: "${GHCR_NAMESPACE:?Missing GHCR_NAMESPACE}"
: "${GHCR_REPOSITORY:?Missing GHCR_REPOSITORY}"
: "${GHCR_PREFIX:?Missing GHCR_PREFIX}"
: "${REPO_ROOT:?Missing REPO_ROOT}"
ghcr_namespace="$(echo "${GHCR_NAMESPACE}" | tr '[:upper:]' '[:lower:]')"
: "${IMAGE_WAIT_SLEEP_SECONDS:?Missing IMAGE_WAIT_SLEEP_SECONDS}"
: "${IMAGE_WAIT_ATTEMPTS:?Missing IMAGE_WAIT_ATTEMPTS}"

max_attempts="${IMAGE_WAIT_ATTEMPTS}"
sleep_seconds="${IMAGE_WAIT_SLEEP_SECONDS}"

mapfile -t mirror_refs < <(
	GHCR_NAMESPACE="${ghcr_namespace}" \
		GHCR_REPOSITORY="${GHCR_REPOSITORY}" \
		GHCR_PREFIX="${GHCR_PREFIX}" \
		REPO_ROOT="${REPO_ROOT}" \
		python - <<'PY'
import os
from pathlib import Path
from cli.contributing.mirror.providers import GHCRProvider
from utils.docker.image_discovery import iter_role_images

provider = GHCRProvider(
    os.environ["GHCR_NAMESPACE"],
    os.environ["GHCR_REPOSITORY"],
    os.environ["GHCR_PREFIX"],
)
repo_root = Path(os.environ["REPO_ROOT"]).resolve()

seen = set()
for img in iter_role_images(repo_root):
    ref = f"{provider.image_base(img)}:{img.version}"
    if ref in seen:
        continue
    seen.add(ref)
    print(ref)
PY
)

total="${#mirror_refs[@]}"
if [[ "${total}" -eq 0 ]]; then
	echo "No mirror refs found. Nothing to wait for."
	exit 0
fi

echo "Fork pull_request detected; waiting for mirrored images from pull_request_target."
echo "Need ${total} mirror refs."

missing=()
for attempt in $(seq 1 "${max_attempts}"); do
	missing=()
	for ref in "${mirror_refs[@]}"; do
		if ! skopeo inspect "docker://${ref}" >/dev/null 2>&1; then
			missing+=("${ref}")
		fi
	done

	if [[ "${#missing[@]}" -eq 0 ]]; then
		echo "All mirrored images are available."
		exit 0
	fi

	echo "[${attempt}/${max_attempts}] Missing ${#missing[@]}/${total} mirror refs. Waiting ${sleep_seconds}s..."
	echo "Example missing: ${missing[0]}"
	sleep "${sleep_seconds}"
done

echo "Timed out waiting for mirrored images." >&2
echo "Still missing (first 20):" >&2
for ref in "${missing[@]:0:20}"; do
	echo " - ${ref}" >&2
done
exit 1
