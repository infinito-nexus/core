#!/usr/bin/env bash
#
# Install & test Infinito via pkgmgr in every distro's virgin container,
# all distros in parallel inside a single CI job (one runner instead of a
# matrix). Each distro gets its own copy of the checkout so the concurrent
# in-container installs never race on the shared working tree.
#
# Inputs via env:
#   NIX_CONFIG          nix access-tokens block (job env).
#   INFINITO_VENV_DIR   venv path inside the container (from default.env).
#   RUNNER_TEMP         runner scratch dir for the per-distro copies.
#   GITHUB_WORKSPACE    the checkout to install and test.
#
# The distro set comes from INFINITO_DISTROS, which the env layer generates
# from the meta/distros.yml SPOT.

set -uo pipefail

: "${NIX_CONFIG:?}"
: "${INFINITO_VENV_DIR:?}"
: "${RUNNER_TEMP:?}"
: "${GITHUB_WORKSPACE:?}"

# shellcheck source=scripts/meta/env/load.sh
source "${GITHUB_WORKSPACE}/scripts/meta/env/load.sh"
: "${INFINITO_DISTROS:?INFINITO_DISTROS must be resolved by scripts/meta/env/load.sh}"
read -r -a distros <<<"${INFINITO_DISTROS}"
declare -A pid

for d in "${distros[@]}"; do
	src="${RUNNER_TEMP}/src-${d}"
	cp -a "${GITHUB_WORKSPACE}/." "${src}"
	docker run --rm \
		-w "/root/" \
		-e NIX_CONFIG="${NIX_CONFIG}" \
		-e INFINITO_VENV_DIR="${INFINITO_VENV_DIR}" \
		-v "${src}:/root/Repositories/github.com/kevinveenbirkenbach/infinito-nexus" \
		"ghcr.io/kevinveenbirkenbach/pkgmgr-${d}:stable" \
		bash -lc '
			set -euo pipefail
			make -C "/root/Repositories/github.com/kevinveenbirkenbach/infinito-nexus" install-system-python
			pkgmgr install infinito --clone-mode shallow --no-verification
			source "${INFINITO_VENV_DIR}/bin/activate"
			infinito --help
		' >"/tmp/install-${d}.log" 2>&1 &
	pid["${d}"]=$!
done

rc_total=0
for d in "${distros[@]}"; do
	rc=0
	wait "${pid[${d}]}" || rc=$?
	echo "::group::${d} (exit ${rc})"
	cat "/tmp/install-${d}.log"
	echo "::endgroup::"
	if [[ "${rc}" -ne 0 ]]; then
		echo "::error::pkgmgr install failed for ${d}"
		rc_total=1
	fi
done

exit "${rc_total}"
