#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
# shellcheck disable=SC1091
source "${REPO_ROOT}/scripts/meta/env/load.sh"

usage() {
	cat <<'USAGE'
Usage:
  cleanup.sh [--days N] [--owner OWNER] [--repository OWNER/REPO] [--distros "arch debian ..."] [--repo-prefix NAME]

Deletes GHCR container package versions that are:
- older than N days (default: 7)
- AND have tags
- AND ALL tags start with "ci-"
- AND are not referenced by active GitHub Actions runs in the repository
So versions with any non-ci tag (e.g. latest, v1.2.3) are preserved.

Robust for USER and ORG owners:
- Tries /orgs/<OWNER>/... first, falls back to /users/<OWNER>/...

Requires:
  - gh CLI authenticated (GH_TOKEN env works)
  - jq installed

Env:
  DAYS, OWNER, REPOSITORY, INFINITO_DISTROS, REPO_PREFIX can be used as defaults.

Examples:
  DAYS=14 OWNER=myorg REPOSITORY=myorg/my-repo REPO_PREFIX=my-repo ./scripts/image/cleanup.sh  # nocheck: self-path-reference
  ./scripts/image/cleanup.sh --days 7 --repository kevinveenbirkenbach/infinito-nexus --distros "arch debian" --repo-prefix infinito-nexus  # nocheck: self-path-reference
USAGE
}

DAYS="${DAYS:-7}"
OWNER="${OWNER:-}"
REPOSITORY="${REPOSITORY:-${GITHUB_REPOSITORY:-}}"
INFINITO_DISTROS="${INFINITO_DISTROS:-}"
REPO_PREFIX="${REPO_PREFIX:-}"

while [[ $# -gt 0 ]]; do
	case "$1" in
	--days)
		DAYS="${2:-}"
		shift 2
		;;
	--owner)
		OWNER="${2:-}"
		shift 2
		;;
	--repository)
		REPOSITORY="${2:-}"
		shift 2
		;;
	--distros)
		INFINITO_DISTROS="${2:-}"
		shift 2
		;;
	--repo-prefix)
		REPO_PREFIX="${2:-}"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "Unknown arg: $1" >&2
		usage
		exit 2
		;;
	esac
done

resolve_repository() {
	if [[ -n "${REPOSITORY:-}" ]]; then
		printf '%s\n' "${REPOSITORY,,}"
		return 0
	fi

	local remote_url
	local remote_path
	if remote_url="$(git config --get remote.origin.url 2>/dev/null)" && [[ -n "${remote_url}" ]]; then
		remote_path="${remote_url%.git}"

		if [[ "${remote_path}" == *://* ]]; then
			remote_path="${remote_path#*://}"
			remote_path="${remote_path#*@}"
			remote_path="${remote_path#*/}"
		elif [[ "${remote_path}" == *:* ]]; then
			remote_path="${remote_path#*:}"
		fi

		if [[ "${remote_path}" == */* ]]; then
			printf '%s\n' "${remote_path,,}"
			return 0
		fi
	fi

	echo "ERROR: REPOSITORY is required (env REPOSITORY/GITHUB_REPOSITORY or --repository)." >&2
	return 1
}

REPOSITORY="$(resolve_repository)"

if [[ -z "${OWNER}" && "${REPOSITORY}" == */* ]]; then
	OWNER="${REPOSITORY%%/*}"
fi

: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: jq not found." >&2
	exit 1
fi

OWNER="$(OWNER="${OWNER:-}" GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" scripts/meta/resolve/repository/owner.sh)"
REPO_PREFIX="$(INFINITO_IMAGE_REPOSITORY="${INFINITO_IMAGE_REPOSITORY:-}" REPO_PREFIX="${REPO_PREFIX:-}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" scripts/meta/resolve/repository/name.sh)"

cutoff="$(date -u -d "${DAYS} days ago" +%s)"
echo ">>> OWNER=${OWNER}"
echo ">>> REPOSITORY=${REPOSITORY}"
echo ">>> DAYS=${DAYS}"
echo ">>> cutoff_epoch=${cutoff}"
echo ">>> INFINITO_DISTROS=${INFINITO_DISTROS}"
echo ">>> REPO_PREFIX=${REPO_PREFIX}"
echo

# --- GH API helpers ---------------------------------------------------------

encode_package_name() {
	local pkg="$1"
	jq -rn --arg v "${pkg}" '$v|@uri'
}

# Try orgs first, fall back to users
gh_api_json() {
	local method="$1"
	shift
	local endpoint="$1"
	shift
	local scope="$1"
	shift # orgs|users

	if [[ "${method}" == "GET" ]]; then
		gh api -H "Accept: application/vnd.github+json" "/${scope}/${OWNER}/${endpoint}" "$@" 2>/dev/null || true
	else
		gh api -X "${method}" -H "Accept: application/vnd.github+json" "/${scope}/${OWNER}/${endpoint}" "$@" 2>/dev/null || true
	fi
}

# Determine whether OWNER is org or user.
# We keep it simple and resilient:
# - prefer orgs endpoint for container packages; if first request returns JSON array, treat as org
# - otherwise try users endpoint; if that returns JSON array, treat as user
# Returns: "orgs" or "users" on stdout.
detect_scope_for_pkg() {
	local pkg="$1"
	local encoded_pkg
	encoded_pkg="$(encode_package_name "${pkg}")"
	local endpoint="packages/container/${encoded_pkg}/versions?per_page=1&page=1"

	local r
	r="$(gh_api_json GET "${endpoint}" orgs)"
	if [[ -n "${r}" ]] && echo "${r}" | jq -e 'type=="array"' >/dev/null 2>&1; then
		echo "orgs"
		return 0
	fi

	r="$(gh_api_json GET "${endpoint}" users)"
	if [[ -n "${r}" ]] && echo "${r}" | jq -e 'type=="array"' >/dev/null 2>&1; then
		echo "users"
		return 0
	fi

	# unknown (no access / package missing). default to orgs (safe), caller will handle empties.
	echo "orgs"
}

list_versions() {
	local pkg="$1"
	local encoded_pkg
	encoded_pkg="$(encode_package_name "${pkg}")"
	local scope
	scope="$(detect_scope_for_pkg "${pkg}")"

	local page=1
	while :; do
		resp="$(gh_api_json GET "packages/container/${encoded_pkg}/versions?per_page=100&page=${page}" "${scope}")"

		if [[ -z "${resp}" ]] || [[ "${resp}" == "[]" ]]; then
			break
		fi

		echo "${resp}"

		count="$(echo "${resp}" | jq 'length')"
		if [[ "${count}" -lt 100 ]]; then
			break
		fi
		page=$((page + 1))
	done
}

delete_version() {
	local pkg="$1"
	local id="$2"
	local encoded_pkg
	encoded_pkg="$(encode_package_name "${pkg}")"

	# Try orgs first
	if gh api -X DELETE -H "Accept: application/vnd.github+json" \
		"/orgs/${OWNER}/packages/container/${encoded_pkg}/versions/${id}" >/dev/null 2>&1; then
		return 0
	fi

	# Fallback to users
	gh api -X DELETE -H "Accept: application/vnd.github+json" \
		"/users/${OWNER}/packages/container/${encoded_pkg}/versions/${id}" >/dev/null
}

list_active_runs() {
	local status

	for status in requested pending waiting queued in_progress; do
		gh api --paginate \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs?status=${status}&per_page=100"
	done |
		jq -sc '
			[
				.[]
				| .workflow_runs[]?
			]
			| unique_by(.id)
		'
}

resolve_active_pr_merge_tags() {
	local active_runs_json="$1"
	local pr_numbers
	local pr_number
	local pr_json
	local merge_sha

	pr_numbers="$(
		echo "${active_runs_json}" |
			jq -r '[ .[] | .pull_requests[]?.number ] | unique[]?'
	)"

	if [[ -z "${pr_numbers}" ]]; then
		return 0
	fi

	while read -r pr_number; do
		[[ -n "${pr_number}" ]] || continue
		pr_json="$(gh api -H "Accept: application/vnd.github+json" "/repos/${REPOSITORY}/pulls/${pr_number}")"
		merge_sha="$(echo "${pr_json}" | jq -r '.merge_commit_sha // empty')"
		if [[ "${merge_sha}" =~ ^[0-9a-f]{40}$ ]]; then
			printf 'ci-%s\n' "${merge_sha}"
		fi
	done <<<"${pr_numbers}"
}

collect_protected_ci_tags() {
	local active_runs_json="$1"

	{
		echo "${active_runs_json}" |
			jq -r '.[] | .head_sha // empty | select(test("^[0-9a-f]{40}$")) | "ci-\(.)"'
		echo "${active_runs_json}" |
			jq -r '.[] | .pull_requests[]?.head.sha // empty | select(test("^[0-9a-f]{40}$")) | "ci-\(.)"'
		resolve_active_pr_merge_tags "${active_runs_json}"
	} |
		awk 'NF' |
		sort -u |
		jq -Rsc '
			split("\n")
			| map(select(length > 0))
		'
}

classify_candidate_versions() {
	local versions_json="$1"
	local protected_tags_json="$2"

	echo "${versions_json}" | jq \
		--argjson cutoff "${cutoff}" \
		--argjson protected_tags "${protected_tags_json}" '
			map(
				. as $v
				| ($v.created_at | fromdateiso8601) as $created
				| ($v.metadata.container.tags // []) as $tags
				| {
						id: $v.id,
						created_at: $v.created_at,
						created_epoch: $created,
						tags: $tags,
						protected_tags: [
							$tags[]?
							| select(. as $tag | $protected_tags | index($tag))
						]
					}
			)
			| map(select(.created_epoch < $cutoff))
			| map(select((.tags | length) > 0))
			| map(select((.tags | all(startswith("ci-")))))
		'
}

# --- main -------------------------------------------------------------------

active_runs="$(list_active_runs)"
active_run_count="$(echo "${active_runs}" | jq 'length')"
echo "Active workflow runs: ${active_run_count}"

if [[ "${active_run_count}" -gt 0 ]]; then
	echo "${active_runs}" | jq -r '
		.[]
		| "ACTIVE run id=\(.id) workflow=\(.name // "unknown") status=\(.status) event=\(.event) head_sha=\(.head_sha // "-")"
	'
fi

protected_ci_tags="$(collect_protected_ci_tags "${active_runs}")"
protected_ci_tag_count="$(echo "${protected_ci_tags}" | jq 'length')"
echo "Protected ci tags from active runs: ${protected_ci_tag_count}"

if [[ "${protected_ci_tag_count}" -gt 0 ]]; then
	echo "${protected_ci_tags}" | jq -r '.[] | "PROTECT tag=\(.)"'
fi

echo

for d in ${INFINITO_DISTROS}; do
	pkg="${REPO_PREFIX}/${d}"
	echo "=== Package: ${pkg} ==="

	all="$(list_versions "${pkg}" | jq -s 'add' 2>/dev/null || echo '[]')"
	total="$(echo "${all}" | jq 'length')"
	echo "Found versions: ${total}"

	if [[ "${total}" -eq 0 ]]; then
		echo "Skip: no versions (or package not found / no access)"
		echo
		continue
	fi

	candidates="$(classify_candidate_versions "${all}" "${protected_ci_tags}")"
	protected_versions="$(echo "${candidates}" | jq '[ .[] | select((.protected_tags | length) > 0) ]')"
	deletable="$(echo "${candidates}" | jq '[ .[] | select((.protected_tags | length) == 0) ]')"

	protected_count="$(echo "${protected_versions}" | jq 'length')"
	del_count="$(echo "${deletable}" | jq 'length')"
	echo "Protected versions: ${protected_count}"
	echo "Deletable versions: ${del_count}"

	if [[ "${protected_count}" -gt 0 ]]; then
		echo "${protected_versions}" | jq -r '
			.[]
			| "SKIP id=\(.id) created_at=\(.created_at) tags=\(.tags|join(",")) protected_by=\(.protected_tags|join(","))"
		'
	fi

	if [[ "${del_count}" -eq 0 ]]; then
		echo "Nothing to delete."
		echo
		continue
	fi

	echo "${deletable}" | jq -r '.[] | "DELETE id=\(.id) created_at=\(.created_at) tags=\(.tags|join(","))"'

	echo "${deletable}" | jq -r '.[].id' | while read -r id; do
		echo "Deleting ${pkg} version id=${id} ..."
		delete_version "${pkg}" "${id}"
	done

	echo "Done: ${pkg}"
	echo
done

echo ">>> Cleanup finished."
