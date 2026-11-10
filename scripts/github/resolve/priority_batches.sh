#!/usr/bin/env bash
#
# Write how many leading batches of the sweep hold priority rows to
# GITHUB_OUTPUT as `count`.
#
# Inputs via env:
#   INPUT_PRIORITY          priority line of the run
#   INPUT_MODE              deploy modes the run draws from
#   INPUT_NETWORK           network axis of the run
#   INPUT_VPN               WireGuard mesh axis of the run
#   INPUT_DISTROS           distro pool of the run ('' = every declared distro)
#   INPUT_FILESYSTEM        filesystem pool of the run ('' = every declared kind)
#   INPUT_ARCHITECTURES     architecture pool of the run ('' = amd64 and arm64)
#   INPUT_LIFECYCLES        lifecycle envelope of the run
#   INFINITO_CI_SWEEP       sweep number driving the axis rotations
#   INFINITO_CI_CHUNK_SIZE  rows one batch holds ('' or 0 = derived)

set -euo pipefail

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

count="$(
	"${PYTHON}" -m cli.meta.ci.matrix --priority-chunks \
		--sweep "${INFINITO_CI_SWEEP}" \
		--priority "${INPUT_PRIORITY}" \
		--modes "${INPUT_MODE}" \
		--network "${INPUT_NETWORK}" \
		--vpn "${INPUT_VPN}" \
		--distros "${INPUT_DISTROS}" \
		--filesystem "${INPUT_FILESYSTEM}" \
		--architectures "${INPUT_ARCHITECTURES}" \
		--lifecycles "${INPUT_LIFECYCLES}"
)"

echo "count=${count}" >>"${GITHUB_OUTPUT}"
echo "count=${count}"
