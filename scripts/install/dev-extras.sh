#!/usr/bin/env bash
# Install the dev extras into the resolved venv once. A stamp inside the
# venv skips reruns until pyproject.toml changes or the venv is recreated,
# so the container-side install disappears together with its venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/python.sh
source scripts/meta/env/python.sh
: "${VENV:?no venv resolved}"

STAMP="${VENV%/}/.dev-extras.stamp"

if [[ ! -w "${VENV}" ]]; then
	echo "[dev-extras] venv not writable (${VENV}); skipping"
	exit 0
fi

if [[ -f "${STAMP}" && "${STAMP}" -nt pyproject.toml ]]; then
	echo "[dev-extras] up to date (${STAMP})"
	exit 0
fi

bash scripts/install/python.sh dev
touch "${STAMP}"
echo "[dev-extras] installed and stamped (${STAMP})"
