#!/usr/bin/env bash
# shellcheck shell=bash
#
# Lint each role's Playwright spec by staging it the same way the
# `test-e2e-playwright` role does at deploy time, then running
# `npx playwright test --list` to validate that:
#
#   - every spec parses without throwing at module-load time
#   - every `require("./personas")` / `require("./service-gating")`
#     resolves against the staged personas tree
#   - every `test(...)` registration is reachable for the runner
#
# `--list` skips the browser launch and any test body, so this is a
# fast structural check (catches refactor regressions like missing
# helpers, broken exports, or syntax errors) — not a functional one.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

: "${INFINITO_WORKER_CPU:?INFINITO_WORKER_CPU must be set (provided by default.env via the env loader)}"

if [[ ! -d "node_modules/@playwright/test" ]]; then
	echo "@playwright/test not installed. Run 'make install-lint' first." >&2
	exit 127
fi

PERSONAS_SRC="${REPO_ROOT}/roles/test-e2e-playwright/files/personas"
SERVICE_GATING_SRC="${REPO_ROOT}/roles/test-e2e-playwright/files/service-gating.js"
PLAYWRIGHT_CONFIG_SRC="${REPO_ROOT}/roles/test-e2e-playwright/files/playwright.config.js"

for asset in "${PERSONAS_SRC}" "${SERVICE_GATING_SRC}" "${PLAYWRIGHT_CONFIG_SRC}"; do
	if [[ ! -e "${asset}" ]]; then
		echo "lint-playwright: missing staging asset: ${asset}" >&2
		exit 2
	fi
done

mapfile -t SPEC_FILES < <(find roles -type f -path '*/files/playwright/playwright.spec.js' | sort)

if [[ ${#SPEC_FILES[@]} -eq 0 ]]; then
	echo "lint-playwright: no Playwright specs found under roles/*/files/playwright/" >&2
	exit 1
fi

STAGE_ROOT="$(mktemp -d -t infinito-lint-playwright.XXXXXX)"
trap 'rm -rf "${STAGE_ROOT}"' EXIT

# Stub env values keyed off the variable-name suffix. Some specs evaluate
# `new URL(process.env.FOO_URL)` or `process.env.BAR.replace(...)` at
# module-load time, so they crash under `--list` unless the env is
# populated. We can't render the Jinja .env templates, but the suffix
# is enough to satisfy URL constructors and `.replace()` calls without
# pretending real values exist.
stub_env_for_key() {
	local key="$1"
	case "${key}" in
	*_URL | *URL) printf '%s' "https://example.test" ;;
	*_DOMAIN | *DOMAIN) printf '%s' "example.test" ;;
	*_SERVICE_ENABLED) printf '%s' "true" ;;
	*_BLOCKED | *BLOCKED) printf '%s' "false" ;;
	*_EMAIL | *EMAIL) printf '%s' "stub@example.test" ;;
	*_JSON | *JSON | *SLUGS | *OVERRIDE) printf '%s' "[]" ;;
	*_HANDLE | *HANDLE) printf '%s' "stubhandle" ;;
	*_PASSWORD | *PASSWORD) printf '%s' "stubpass" ;;
	*_TOKEN | *TOKEN | *_KEY | *KEY) printf '%s' "stubtoken" ;;
	*_USERNAME | *USERNAME) printf '%s' "stubuser" ;;
	*) printf '%s' "stub" ;;
	esac
}

# Reset reporter output paths to a per-role writable location. The
# central playwright.config.js hard-codes `/reports/...` (only writable
# inside the Playwright container), which spams `ENOENT: mkdir`
# stderr noise under lint. Re-pointing them keeps the run silent and
# self-cleaning under STAGE_ROOT.
config_stub() {
	cat <<-'EOF_CFG'
		const base = require("./playwright.config.original.js");
		const path = require("path");
		const here = __dirname;
		module.exports = {
		  ...base,
		  outputDir: path.join(here, "test-results"),
		  reporter: [["list"]],
		};
	EOF_CFG
}

# Lint a single role end-to-end: stage assets, derive stub env, run
# `npx playwright test --list`. All output goes to stdout/stderr of the
# caller, so the parallel driver redirects it into a per-role log file.
lint_one_role() {
	local spec="$1"
	local role_files_dir
	local role
	role_files_dir="$(dirname "${spec}")"
	role="${spec#roles/}"
	role="${role%%/*}"

	echo "::group::lint-playwright ${role}"

	local stage_dir="${STAGE_ROOT}/${role}"
	local tests_dir="${stage_dir}/tests"
	mkdir -p "${tests_dir}/personas/utils"

	cp -f "${PLAYWRIGHT_CONFIG_SRC}" "${stage_dir}/playwright.config.original.js"
	config_stub >"${stage_dir}/playwright.config.js"

	cp -f "${role_files_dir}"/*.js "${tests_dir}/"
	cp -f "${SERVICE_GATING_SRC}" "${tests_dir}/service-gating.js"
	cp -f "${PERSONAS_SRC}"/*.js "${tests_dir}/personas/"
	cp -f "${PERSONAS_SRC}"/utils/*.js "${tests_dir}/personas/utils/"

	ln -sfn "${REPO_ROOT}/node_modules" "${stage_dir}/node_modules"

	local stub_env=()
	local env_template="roles/${role}/templates/playwright.env.j2"
	if [[ -f "${env_template}" ]]; then
		local key
		while IFS= read -r key; do
			[[ -z "${key}" ]] && continue
			stub_env+=("${key}=$(stub_env_for_key "${key}")")
		done < <(grep -oE '^[A-Z][A-Z0-9_]+=' "${env_template}" | sed 's/=$//' | sort -u)
	fi

	local rc=0
	(cd "${stage_dir}" && env "${stub_env[@]+"${stub_env[@]}"}" npx --no-install playwright test --list) || rc=$?
	echo "::endgroup::"
	return "${rc}"
}

# Dispatch every spec through `lint_one_role` with up to
# INFINITO_WORKER_CPU concurrent workers. Output is captured per role
# and replayed in `SPEC_FILES` order in the second pass so stdout stays
# deterministic regardless of completion order.
log_dir="${STAGE_ROOT}/logs"
mkdir -p "${log_dir}"

total_specs=${#SPEC_FILES[@]}
n_workers="${INFINITO_WORKER_CPU}"
if ((n_workers > total_specs)); then n_workers="${total_specs}"; fi

active=0
declare -A pid_to_role=()
declare -A role_rc=()

drain_completion() {
	local pid=""
	local rc=0
	wait -n -p pid || rc=$?
	local role="${pid_to_role[${pid}]}"
	role_rc["${role}"]="${rc}"
	active=$((active - 1))
}

for spec in "${SPEC_FILES[@]}"; do
	while ((active >= n_workers)); do
		drain_completion
	done
	role="${spec#roles/}"
	role="${role%%/*}"
	lint_one_role "${spec}" >"${log_dir}/${role}.log" 2>&1 &
	pid_to_role[$!]="${role}"
	active=$((active + 1))
done

while ((active > 0)); do
	drain_completion
done

failed_roles=()
for spec in "${SPEC_FILES[@]}"; do
	role="${spec#roles/}"
	role="${role%%/*}"
	cat "${log_dir}/${role}.log"
	if [[ "${role_rc[${role}]:-0}" -ne 0 ]]; then
		failed_roles+=("${role}")
		echo "::error file=${spec}::lint-playwright: 'playwright test --list' failed for ${role}"
	fi
done

if [[ ${#failed_roles[@]} -gt 0 ]]; then
	echo "lint-playwright FAILED for ${#failed_roles[@]}/${total_specs} role(s): ${failed_roles[*]}" >&2
	exit 1
fi

echo "lint-playwright OK (${total_specs} spec(s) parsed, ${n_workers} parallel worker(s))"
