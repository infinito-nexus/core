#!/usr/bin/env bash
# Rerun a role-local Playwright spec against the live running stack.
#
# Preconditions:
#   - The role has been deployed at least once, so the Playwright project is
#     staged under $TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<role> with a rendered
#     .env file.
#   - The application under test is still running.
#
# The stage base comes from INFINITO_PLAYWRIGHT_STAGE_BASE_DIR (env handler);
# DiD nodes run this without a generated .env, so the script falls back to
# the same role-vars SPOT the handler reads.
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

stage_base="${INFINITO_PLAYWRIGHT_STAGE_BASE_DIR:-}"
if [[ -z "$stage_base" ]]; then
	stage_base="$(awk '$1 == "TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR:" {gsub(/"/, "", $2); print $2}' \
		"$repo_root/roles/test-e2e-playwright/vars/main.yml")"
fi
[[ -n "$stage_base" ]] || {
	echo "TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR missing in roles/test-e2e-playwright/vars/main.yml (SPOT)" >&2
	exit 2
}
reports_base="${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR:?source scripts/meta/env/load.sh or run via make}"

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
helper_src="$repo_root/roles/test-e2e-playwright/files/service-gating.js"
if [[ -f "$helper_src" ]]; then
	cp "$helper_src" "$stage_dir/tests/service-gating.js"
fi
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

for sub in addons fixtures; do
	sub_dir="$role_playwright_dir/$sub"
	[[ -d "$sub_dir" ]] || continue
	mkdir -p "$stage_dir/tests/$sub"
	for sub_file in "$sub_dir"/*.js; do
		[[ -f "$sub_file" ]] || continue
		cp "$sub_file" "$stage_dir/tests/$sub/$(basename "$sub_file")"
	done
done

cmd="${TEST_E2E_PLAYWRIGHT_COMMAND:-npm install --no-fund --no-audit && npx playwright test${*:+ $*}}"

if [[ "${TEST_E2E_PLAYWRIGHT_NETWORK_HOST:-}" == "true" ]]; then
	net_args=(--network host)
else
	net_args=(--add-host=host.docker.internal:host-gateway)
fi

exec docker run --rm \
	--ipc=host --shm-size=1g \
	"${net_args[@]}" \
	--env-file "$env_file" \
	-v "$stage_dir:/e2e" \
	-v "$stage_dir/volume:/volume" \
	-v "$reports_dir:/reports" \
	-w /e2e \
	"$image" \
	/bin/bash -lc "$cmd"
