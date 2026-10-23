#!/usr/bin/env bash
# Args:
#   $1  image reference to pull
# Output: "pulled" when the pull changed the local image, "present" when the host already had it.
set -euo pipefail

REF="${1:?image reference required}"

before="$(docker image inspect --format '{{.Id}}' "$REF" 2>/dev/null)" || before=""
docker pull --quiet "$REF" >/dev/null
after="$(docker image inspect --format '{{.Id}}' "$REF")"

if [[ "$before" == "$after" ]]; then
	echo present
else
	echo pulled
fi
