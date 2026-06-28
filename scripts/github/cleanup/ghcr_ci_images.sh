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
dry_run="${DRY_RUN:-false}"

if [[ ! "${max_age_days}" =~ ^[0-9]+$ ]]; then
	echo "ERROR: MAX_AGE_DAYS must be a non-negative integer." >&2
	exit 1
fi

if [[ -z "${tag_prefix}" ]]; then
	echo "ERROR: TAG_PREFIX must not be empty." >&2
	exit 1
fi

for tool in gh jq; do
	if ! command -v "${tool}" >/dev/null 2>&1; then
		echo "ERROR: ${tool} not found." >&2
		exit 1
	fi
done

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

classify_version() {
	local version="${1}" cutoff_ts="${2}"
	local tags updated_ts

	tags="$(jq -r '.tags[]?' <<<"${version}")"
	[[ -n "${tags}" ]] || {
		echo "keep:untagged"
		return 0
	}
	grep -Eq "^(latest|v[0-9].*)$" <<<"${tags}" && {
		echo "keep:release-tag"
		return 0
	}
	grep -q "^${tag_prefix}" <<<"${tags}" || {
		echo "keep:no-ci-tag"
		return 0
	}

	updated_ts="$(date -u -d "$(jq -r '.updated_at' <<<"${version}")" +%s)"
	[[ "${updated_ts}" -lt "${cutoff_ts}" ]] || {
		echo "keep:too-new"
		return 0
	}

	echo "delete"
}

cutoff="$(date -u -d "${max_age_days} days ago" +%s)"

echo "GHCR CI image cleanup"
echo "  org=${ORG} tag-prefix=${tag_prefix} max-age=${max_age_days}d dry-run=${dry_run}"
echo "  cutoff=$(date -u -d "@${cutoff}" +%Y-%m-%dT%H:%M:%SZ) (delete ${tag_prefix}* versions without a semver/latest tag, older than this)"

total_scanned=0
total_deleted=0
declare -A kept_reasons=()

while IFS= read -r package; do
	package="${package#"${package%%[![:space:]]*}"}"
	package="${package%"${package##*[![:space:]]}"}"
	[[ -n "${package}" ]] || continue

	encoded_package="$(encode_package_name "${package}")"

	pkg_scanned=0
	pkg_deleted=0

	echo "== ${package} =="

	while IFS= read -r version; do
		[[ -n "${version}" ]] || continue
		pkg_scanned=$((pkg_scanned + 1))

		decision="$(classify_version "${version}" "${cutoff}")"

		if [[ "${decision}" != "delete" ]]; then
			kept_reasons["${decision}"]=$((${kept_reasons["${decision}"]:-0} + 1))
			continue
		fi

		id="$(jq -r '.id' <<<"${version}")"
		updated_at="$(jq -r '.updated_at' <<<"${version}")"
		tags_csv="$(jq -r '[.tags[]?] | join(",")' <<<"${version}")"

		if [[ "${dry_run}" == "true" ]]; then
			echo "  would delete id=${id} tags=${tags_csv} updated=${updated_at}"
		else
			echo "  deleting id=${id} tags=${tags_csv} updated=${updated_at}"
			gh api \
				--method DELETE \
				"/orgs/${ORG}/packages/container/${encoded_package}/versions/${id}"
		fi
		pkg_deleted=$((pkg_deleted + 1))
	done < <(gh api --paginate \
		"/orgs/${ORG}/packages/container/${encoded_package}/versions" \
		--jq '.[] | {id: .id, updated_at: .updated_at, tags: .metadata.container.tags}' |
		jq -c '.')

	echo "  -> scanned ${pkg_scanned}, deleted ${pkg_deleted}"
	total_scanned=$((total_scanned + pkg_scanned))
	total_deleted=$((total_deleted + pkg_deleted))
done < <(resolve_packages)

echo "== Summary =="
echo "  scanned ${total_scanned} versions, deleted ${total_deleted}"
for reason in "${!kept_reasons[@]}"; do
	echo "  kept ${kept_reasons[${reason}]} (${reason})"
done

if [[ "${total_deleted}" -eq 0 ]]; then
	echo "  no versions matched the deletion criteria"
fi
