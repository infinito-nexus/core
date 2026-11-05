#!/usr/bin/env bash
#
# Compute the matrix JSON + effective image_tag for images-build-ci and
# write both to $GITHUB_OUTPUT. Replaces the inline `run:` block of the
# "Compute matrix JSON" step.
#
# Usage:
#   images_build_outputs.sh "<distros>" "<image_tag_override>" "<architectures>"
set -euo pipefail

distros="${1:-}"
override="${2:-}"
architectures="${3:-}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"
json="$(bash "${script_dir}/distros_matrix.sh" "${distros}")"
arch_json="$(cd "${repo_root}" && "${PYTHON:-python3}" -m cli.meta.ci.architectures "${architectures}")"

if [[ -n "${override}" ]]; then
	image_tag="${override}"
else
	: "${GITHUB_SHA:?GITHUB_SHA must be set when no image_tag override is provided}"
	image_tag="ci-${GITHUB_SHA}"
fi

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"
{
	echo "matrix=${json}"
	echo "image_tag=${image_tag}"
	echo "architectures=${arch_json}"
} >>"${GITHUB_OUTPUT}"

echo "Using matrix: ${json}"
echo "Using image tag: ${image_tag}"
echo "Using architectures: ${arch_json}"
