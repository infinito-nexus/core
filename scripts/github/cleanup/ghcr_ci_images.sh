#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
# shellcheck disable=SC1091
source "${REPO_ROOT}/scripts/meta/env/load.sh"

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${ORG:?Missing ORG}"

package_prefix="${PACKAGE_PREFIX:-core}"
max_age_days="${MAX_AGE_DAYS:-30}"
tag_prefix="${TAG_PREFIX:-ci-}"

if [[ ! "${max_age_days}" =~ ^[0-9]+$ ]]; then
	echo "ERROR: MAX_AGE_DAYS must be a non-negative integer." >&2
	exit 1
fi

if [[ -z "${tag_prefix}" ]]; then
	echo "ERROR: TAG_PREFIX must not be empty." >&2
	exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: jq not found." >&2
	exit 1
fi

encode_package_name() {
	local package="${1}"
	jq -rn --arg value "${package}" '$value | @uri'
}

resolve_packages() {
	if [[ -n "${PACKAGES:-}" ]]; then
		printf '%s\n' "${PACKAGES}"
		return 0
	fi

	: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"

	for distro in ${INFINITO_DISTROS}; do
		printf '%s/%s\n' "${package_prefix}" "${distro}"
	done
}

is_deletable_ci_version() {
	local version="${1}"
	local tags

	tags="$(jq -r '.tags[]?' <<<"${version}")"

	[[ -n "${tags}" ]] || return 1

	# Keep release tags even when the version also has ci-* tags.
	grep -q "^${tag_prefix}" <<<"${tags}" || return 1
	grep -Eq "^(latest|v.*)$" <<<"${tags}" && return 1
	grep -vq "^${tag_prefix}" <<<"${tags}" && return 1

	return 0
}

cutoff="$(date -u -d "${max_age_days} days ago" +%s)"

while IFS= read -r package; do
	package="${package#"${package%%[![:space:]]*}"}"
	package="${package%"${package##*[![:space:]]}"}"
	[[ -n "${package}" ]] || continue

	encoded_package="$(encode_package_name "${package}")"

	gh api --paginate \
		"/orgs/${ORG}/packages/container/${encoded_package}/versions" \
		--jq '.[] | {id: .id, updated_at: .updated_at, tags: .metadata.container.tags}' |
		jq -c '.' |
		while IFS= read -r version; do
			id="$(jq -r '.id' <<<"${version}")"
			updated_at="$(jq -r '.updated_at' <<<"${version}")"
			updated_ts="$(date -u -d "${updated_at}" +%s)"

			if [[ "${updated_ts}" -ge "${cutoff}" ]]; then
				continue
			fi

			is_deletable_ci_version "${version}" || continue

			echo "Deleting ${package} version ${id} updated at ${updated_at}"
			gh api \
				--method DELETE \
				"/orgs/${ORG}/packages/container/${encoded_package}/versions/${id}"
		done
done < <(resolve_packages)
