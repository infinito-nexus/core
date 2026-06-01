#!/usr/bin/env bash
# Rerun a role-local Playwright spec against the live running stack.
#
# Preconditions:
#   - The role has been deployed at least once, so the Playwright project is
#     staged under $TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<role> with a rendered
#     .env file.
#   - The application under test is still running.
#
# This script intentionally does NOT re-render .env. It restages the
# role-local Playwright files (spec + companions) from the repo and reruns
# Playwright via the same container image the deploy-time runner uses.
#
# Usage:
#   scripts/tests/e2e/rerun-spec.sh <role> [playwright args...]  # nocheck: self-path-reference
#   scripts/tests/e2e/rerun-spec.sh web-app-nextcloud --grep "talk admin"  # nocheck: self-path-reference
set -euo pipefail

if [[ $# -lt 1 ]]; then
	echo "usage: $0 <role> [playwright args...]" >&2
	exit 2
fi

role="$1"
shift

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
role_playwright_dir="$repo_root/roles/$role/files/playwright"
spec_src="$role_playwright_dir/playwright.spec.js"
services_yml="$repo_root/roles/test-e2e-playwright/meta/services.yml"

stage_base="${TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR:-/tmp/test-e2e-playwright}"
reports_base="${TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR:-/var/lib/infinito/logs/test-e2e-playwright}"

stage_dir="$stage_base/$role"
reports_dir="$reports_base/$role"
env_file="$stage_dir/.env"

[[ -f "$spec_src" ]] || {
	echo "missing spec: $spec_src" >&2
	exit 1
}
[[ -d "$stage_dir" ]] || {
	echo "missing staging dir (run deploy first): $stage_dir" >&2
	exit 1
}
[[ -f "$env_file" ]] || {
	echo "missing rendered env (run deploy first): $env_file" >&2
	exit 1
}

image="${TEST_E2E_PLAYWRIGHT_IMAGE:-}"
if [[ -z "$image" ]]; then
	base_image="$(awk '/^[[:space:]]*image:[[:space:]]/{print $2; exit}' "$services_yml")"
	tag="$(awk -F'"' '/^[[:space:]]*version:[[:space:]]/{print $2; exit}' "$services_yml")"
	image="${base_image}:${tag}"
fi

command -v docker >/dev/null || {
	echo "docker not found in PATH" >&2
	exit 1
}

mkdir -p "$stage_dir/tests" "$stage_dir/volume" "$reports_dir"
for role_js in "$role_playwright_dir"/*.js; do
	[[ -f "$role_js" ]] || continue
	cp "$role_js" "$stage_dir/tests/$(basename "$role_js")"
done
# Stage the shared service-gating helper so the spec can require("./service-gating").
helper_src="$repo_root/roles/test-e2e-playwright/files/service-gating.js"
if [[ -f "$helper_src" ]]; then
	cp "$helper_src" "$stage_dir/tests/service-gating.js"
fi
# Stage the shared persona-flow helpers.
# personas/ holds the persona flow runners (biber.js, admin.js, guest.js,
# index.js) at the top and every helper module under personas/utils/. Copy
# both levels so a spec can `require("./personas")` (resolves to
# personas/index.js) or directly `require("./personas/<flow>")` /
# `require("./personas/utils/<helper>")` for a subset.
personas_dir="$repo_root/roles/test-e2e-playwright/files/personas"
if [[ -d "$personas_dir" ]]; then
	mkdir -p "$stage_dir/tests/personas/utils"
	for persona_file in "$personas_dir"/*.js; do
		[[ -f "$persona_file" ]] || continue
		cp "$persona_file" "$stage_dir/tests/personas/$(basename "$persona_file")"
	done
	for util_file in "$personas_dir"/utils/*.js; do
		[[ -f "$util_file" ]] || continue
		cp "$util_file" "$stage_dir/tests/personas/utils/$(basename "$util_file")"
	done
fi

cmd="${TEST_E2E_PLAYWRIGHT_COMMAND:-npm install --no-fund --no-audit && npx playwright test${*:+ $*}}"

exec docker run --rm \
	--ipc=host --shm-size=1g \
	--add-host=host.docker.internal:host-gateway \
	--env-file "$env_file" \
	-v "$stage_dir:/e2e" \
	-v "$stage_dir/volume:/volume" \
	-v "$reports_dir:/reports" \
	-w /e2e \
	"$image" \
	/bin/bash -lc "$cmd"
