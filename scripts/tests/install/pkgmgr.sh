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
#   INFINITO_DISTROS    distro list; defaults to the SPOT in default.env.

set -uo pipefail

: "${NIX_CONFIG:?}"
: "${INFINITO_VENV_DIR:?}"
: "${RUNNER_TEMP:?}"
: "${GITHUB_WORKSPACE:?}"

if [[ -z "${INFINITO_DISTROS:-}" ]]; then
	INFINITO_DISTROS="$(awk -F= '/^INFINITO_DISTROS=/{v=$2; gsub(/^"|"$/,"",v); print v; exit}' "${GITHUB_WORKSPACE}/default.env")"
fi
: "${INFINITO_DISTROS:?}"
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
