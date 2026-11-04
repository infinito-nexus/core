#!/bin/bash

set -euo pipefail

# Param keep_label: <key>=<value> of the image label whose images survive the image prune.
keep_label="${1:?usage: prune.sh <keep label key=value>}"

echo "Docker disk usage before cleanup:"
container system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

container container prune -f || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container image prune -af --filter "label!=${keep_label}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container volume prune -f || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

container buildx prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
container builder prune -af || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo "Docker disk usage after cleanup:"
container system df || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
