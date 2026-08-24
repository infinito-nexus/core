#!/usr/bin/env bash
set -euo pipefail

# Resolve the CI deploy matrix for one chunk of one sweep. The pipeline itself
# (two discovery queries, the axis rotations, the chunk split) lives in
# cli.meta.ci.matrix, shared with the deploy-plan table, so the matrix this
# emits and the plan the summary renders can never disagree. Every entry is one
# role#variant row carrying the mode, onion state, distro and filesystem it was
# assigned.
#
# Inputs via env (defaults live in default.env, the single source of truth):
#   INFINITO_CI_CHUNK              chunk index to emit (required)
#   INFINITO_CI_SWEEP              sweep number driving the axis rotations
#   INFINITO_CI_OFFSET             regular rows to skip before filling the chunks
#   INFINITO_MODES                 'auto' or a subset of 'host compose swarm'
#   INFINITO_WHITELIST             optional space-separated app ids to keep
#   INFINITO_PRIORITY              optional space-separated app ids to lead
#   INFINITO_TOR                   auto|enforced|exclusive|disabled
#   INFINITO_DISTROS               distro pool the rows are spread over; empty: all
#   INFINITO_DOCKER_FILESYSTEM_ALLOWED  filesystem pool; empty: all
#   INFINITO_LIFECYCLES            lifecycle envelope for discovery
#   INFINITO_DISCOVERY_SORT        complexity --sort spec (coverage-first)
#   INFINITO_REQUIRED_STORAGE      per-runner CI storage budget
#   INFINITO_APP_DISCOVERY_RUNNER  host|docker
#
# Output: JSON array of matrix entries to stdout (single line, always valid).

PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi

json_compact_array() {
	jq -c 'if type=="array" then . else [] end'
}

run_meta_cli() {
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

matrix_json="$(
	run_meta_cli -m cli.meta.ci.matrix \
		--index "${INFINITO_CI_CHUNK:?INFINITO_CI_CHUNK must be set to the chunk index to emit}" \
		--sweep "${INFINITO_CI_SWEEP}" \
		--offset "${INFINITO_CI_OFFSET}" \
		--modes "${INFINITO_MODES}" \
		--whitelist "${INFINITO_WHITELIST}" \
		--priority "${INFINITO_PRIORITY}" \
		--lifecycles "${INFINITO_LIFECYCLES}" \
		--tor "${INFINITO_TOR}" \
		--distros "${INFINITO_DISTROS}" \
		--filesystem "${INFINITO_DOCKER_FILESYSTEM_ALLOWED}"
)"

if [[ -n "${GITHUB_ACTIONS:-}" && -z "${ACT:-}" ]]; then
	required_storage="${INFINITO_REQUIRED_STORAGE}"

	mapfile -t roles < <(printf '%s\n' "${matrix_json}" | jq -r '.[].apps' | sort -u)
	if [[ "${#roles[@]}" -gt 0 ]]; then
		run_meta_cli \
			-m cli.meta.roles.applications.sufficient_storage \
			--roles "${roles[@]}" \
			--required-storage "${required_storage}" \
			--warnings \
			--format json \
			>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

		kept_roles="$(
			run_meta_cli \
				-m cli.meta.roles.applications.sufficient_storage \
				--roles "${roles[@]}" \
				--required-storage "${required_storage}" \
				--format json |
				json_compact_array
		)"

		matrix_json="$(
			printf '%s' "${matrix_json}" |
				jq -c --argjson keep "${kept_roles}" \
					'map(select(.apps as $a | $keep | index($a) != null))'
		)"
	fi
fi

printf '%s\n' "${matrix_json}" | json_compact_array
