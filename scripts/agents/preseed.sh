#!/usr/bin/env bash
set -euo pipefail

# Host-pull the agents bundle's large images before the deploy, so images over
# the registry cache transfer limit (for example the Ollama image) are present
# in the local daemon and the deploy does not transfer them.
# Inputs (make vars):
#   images - space-separated image refs to host-pull; empty means nothing to
#            preseed (the deploy then pulls its images itself).

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${_repo_root}"

images="${images:-}"
if [ -z "${images// /}" ]; then
	echo "agents-preseed: no images given; nothing to host-pull."
	echo "Pass the large image refs the agents bundle needs, e.g. make agents-preseed images=\"<ref> <ref>\"."
	exit 0
fi

read -ra _images <<<"${images}"
for image in "${_images[@]}"; do
	bash scripts/github/runner/pull_with_retry.sh "${image}"
done
