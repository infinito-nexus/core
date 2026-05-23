#!/usr/bin/env bash
set -euo pipefail

# Purpose (SRP): Return JSON list of apps based on deployment type,
# optionally filtered by lifecycle and CI storage constraints.
#
# Inputs via env:
#   INFINITO_DEPLOY_TYPE   = server|workstation|universal (required)
#   INFINITO_WHITELIST = optional space-separated list of app ids to keep
#
# Output:
#   JSON array to stdout (single line, always valid)

: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE is required (server|workstation|universal)}"

PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# ------------------------------------------------------------
# Load default environment (safe if already loaded via BASH_ENV)
# ------------------------------------------------------------
if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi

# ------------------------------------------------------------
# Helpers (JSON-only, no text roundtrips)
# ------------------------------------------------------------

json_compact_array() {
	# Read JSON from stdin, ensure it's an array, output compact single-line JSON.
	jq -c 'if type=="array" then . else [] end'
}

jq_exclude_regex() {
	# Args: regex
	# Reads JSON array from stdin, filters out entries matching regex, outputs compact JSON.
	local re="$1"
	if [[ -z "${re}" ]]; then
		json_compact_array
		return 0
	fi
	jq -c --arg re "${re}" 'map(select(test($re) | not))'
}

jq_whitelist_filter() {
	# Args: whitelist (space-separated app ids)
	# Reads JSON array from stdin, keeps only entries in whitelist, outputs compact JSON.
	local wl="${1:-}"
	if [[ -z "${wl// /}" ]]; then
		json_compact_array
		return 0
	fi
	local wl_json
	wl_json="$(printf '%s' "${wl}" | jq -Rc 'split(" ") | map(select(length>0))')"
	jq -c --argjson wl "${wl_json}" 'map(select(. as $a | ($wl | index($a)) != null))'
}

run_meta_cli() {
	# Dispatch on INFINITO_APP_DISCOVERY_RUNNER:
	#   host   -- invoke the venv python directly (no container overhead)
	#   docker -- exec inside the running infinito compose container
	case "${INFINITO_APP_DISCOVERY_RUNNER:?INFINITO_APP_DISCOVERY_RUNNER must be set}" in
	host)
		"${PYTHON}" "$@"
		;;
	docker)
		NIX_CONFIG="${NIX_CONFIG:-}" \
			INFINITO_DISTRO="${INFINITO_DISTRO}" \
			docker compose exec -T infinito "${PYTHON}" "$@"
		;;
	*)
		echo "apps.sh: unknown INFINITO_APP_DISCOVERY_RUNNER='${INFINITO_APP_DISCOVERY_RUNNER}' (expected: host|docker)" >&2
		exit 2
		;;
	esac
}

# ------------------------------------------------------------
# Lifecycle handling (always-on, original set)
# ------------------------------------------------------------
lifecycles_args=(--lifecycles alpha beta rc stable)

# ------------------------------------------------------------
# 1) Get JSON list from container (keep as JSON)
# ------------------------------------------------------------
apps_json="$(
	run_meta_cli \
		-m cli.meta.roles.applications.type \
		--format json \
		--type "${INFINITO_DEPLOY_TYPE}" \
		"${lifecycles_args[@]}" |
		json_compact_array
)"

# ------------------------------------------------------------
# 2) Global hard excludes (regex over app ids)
# ------------------------------------------------------------
# TODO: Remove exclude condition
apps_json="$(
	printf '%s\n' "${apps_json}" |
		jq_exclude_regex '^(web-app-oauth2-proxy)$'
)"

# ------------------------------------------------------------
# 3) CI storage filter (JSON-only)
# ------------------------------------------------------------
if [[ -n "${GITHUB_ACTIONS:-}" && -z "${ACT:-}" ]]; then
	required_storage="60GB"

	# Extract roles from JSON to pass as args (safe: one per line -> bash array)
	mapfile -t roles < <(printf '%s\n' "${apps_json}" | jq -r '.[]')
	if [[ "${#roles[@]}" -gt 0 ]]; then
		# Warnings pass (best-effort)
		run_meta_cli \
			-m cli.meta.roles.applications.sufficient_storage \
			--roles "${roles[@]}" \
			--required-storage "${required_storage}" \
			--warnings \
			--format json \
			>/dev/null || true

		# Real filter (JSON output)
		apps_json="$(
			run_meta_cli \
				-m cli.meta.roles.applications.sufficient_storage \
				--roles "${roles[@]}" \
				--required-storage "${required_storage}" \
				--format json |
				json_compact_array
		)"
	fi
fi

# ------------------------------------------------------------
# 3b) Optional whitelist filter (space-separated list of app ids)
# ------------------------------------------------------------
apps_json="$(
	printf '%s\n' "${apps_json}" |
		jq_whitelist_filter "${INFINITO_WHITELIST:-}"
)"

# ------------------------------------------------------------
# 4) Final safety: compact JSON array, single line
# ------------------------------------------------------------
printf '%s\n' "${apps_json}" | json_compact_array
