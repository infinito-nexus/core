#!/usr/bin/env bash
# Remove the shared test runner of this checkout's toolchain image together with
# its inner Docker volume; the next test or lint call starts a new one.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/../../.."
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
# shellcheck source=scripts/tests/runner/lib.sh
source scripts/tests/runner/lib.sh

name="$(infinito_test_runner_name "$(infinito_test_runner_image)")"
if docker inspect "${name}" >/dev/null 2>&1; then
	docker rm -f -v "${name}" >/dev/null
	echo ">>> Removed the shared test runner ${name}"
else
	echo ">>> No shared test runner ${name} exists"
fi
