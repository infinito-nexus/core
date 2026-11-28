#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/../../.."
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
# shellcheck source=scripts/tests/runner/lib.sh
source scripts/tests/runner/lib.sh

image="$(infinito_test_runner_image)"
name="$(infinito_test_runner_name "${image}")"
if docker inspect "${name}" >/dev/null 2>&1; then
	running="$(docker inspect --format '{{.State.Running}}' "${name}")"
	roots="$(docker inspect --format "{{index .Config.Labels \"${_infinito_test_runner_roots_label}\"}}" "${name}")"
	echo ">>> Shared test runner ${name} from ${image}: running=${running}, worktree roots ${roots}"
else
	echo ">>> No shared test runner ${name} exists; the next test or lint call starts it from ${image}"
fi
