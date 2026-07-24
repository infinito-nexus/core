#!/usr/bin/env bash
#
# Install & test Infinito via the Makefile in every distro's virgin
# container, all distros in parallel inside a single CI job (one runner
# instead of a matrix). Each distro gets its own copy of the checkout so
# the concurrent in-container installs never race on the shared tree.
#
# Inputs via env:
#   NIX_CONFIG          nix access-tokens block (job env).
#   INFINITO_SRC_DIR    checkout mount point inside the container.
#   INFINITO_VENV_DIR   venv path inside the container (from default.env).
#   RUNNER_TEMP         runner scratch dir for the per-distro copies.
#   GITHUB_WORKSPACE    the checkout to install and test.

set -uo pipefail

: "${NIX_CONFIG:?}"
: "${INFINITO_SRC_DIR:?}"
: "${INFINITO_VENV_DIR:?}"
: "${RUNNER_TEMP:?}"
: "${GITHUB_WORKSPACE:?}"

distros=(arch debian ubuntu fedora centos)
declare -A pid

for d in "${distros[@]}"; do
	src="${RUNNER_TEMP}/src-${d}"
	cp -a "${GITHUB_WORKSPACE}/." "${src}"
	docker run --rm \
		-e NIX_CONFIG="${NIX_CONFIG}" \
		-e INFINITO_SRC_DIR="${INFINITO_SRC_DIR}" \
		-e INFINITO_VENV_DIR="${INFINITO_VENV_DIR}" \
		-v "${src}:${INFINITO_SRC_DIR}" \
		-w "${INFINITO_SRC_DIR}" \
		"ghcr.io/kevinveenbirkenbach/pkgmgr-${d}-virgin:stable" \
		bash -lc '
			set -euo pipefail
			make install
			make setup
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
		echo "::error::make install failed for ${d}"
		rc_total=1
	fi
done

exit "${rc_total}"
