#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${WORKFLOW_FILE:?Missing WORKFLOW_FILE}"
: "${TARGET_EVENT:?Missing TARGET_EVENT}"
: "${PR_NUMBER:?Missing PR_NUMBER}"
: "${IMAGE_TAG:?Missing IMAGE_TAG}"
: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS}"
: "${WAIT_ATTEMPTS:?Missing WAIT_ATTEMPTS}"
: "${WAIT_SLEEP_SECONDS:?Missing WAIT_SLEEP_SECONDS}"

for bin in docker gh jq; do
	if ! command -v "${bin}" >/dev/null 2>&1; then
		echo "ERROR: ${bin} not found." >&2
		exit 1
	fi
done

repo_owner="$(scripts/meta/resolve/repository/owner.sh)"
repo_name="$(scripts/meta/resolve/repository/name.sh)"
pr_head_sha="${PR_HEAD_SHA:-}"
pr_updated_at="${PR_UPDATED_AT:-}"
pr_updated_at_floor=""
last_run_state=""
last_run_id=""

if [[ -n "${pr_updated_at}" ]]; then
	# GitHub can report the PR update slightly after the matching workflow run was created.
	if ! pr_updated_at_floor="$(date -u -d "${pr_updated_at} - 300 seconds" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)"; then
		echo "WARN: Could not relax PR_UPDATED_AT=${pr_updated_at}; using the raw timestamp." >&2
		pr_updated_at_floor="${pr_updated_at}"
	fi
fi

read -r -a distros_raw <<<"${INFINITO_DISTROS}"
distros=()
for distro in "${distros_raw[@]}"; do
	[[ -n "${distro}" ]] || continue
	distros+=("${distro}")
done

if [[ "${#distros[@]}" -eq 0 ]]; then
	echo "ERROR: INFINITO_DISTROS did not contain any entries." >&2
	exit 1
fi

build_image_refs() {
	local distro

	for distro in "${distros[@]}"; do
		printf 'ghcr.io/%s/%s/%s:%s\n' "${repo_owner}" "${repo_name}" "${distro}" "${IMAGE_TAG}"
	done
}

mapfile -t image_refs < <(build_image_refs)

find_matching_run() {
	gh api --paginate \
		-H "Accept: application/vnd.github+json" \
		"/repos/${GITHUB_REPOSITORY}/actions/workflows/${WORKFLOW_FILE}/runs?event=${TARGET_EVENT}&per_page=100" |
		jq -sc \
			--argjson pr_number "${PR_NUMBER}" \
			--arg pr_head_sha "${pr_head_sha}" \
			--arg pr_updated_at_floor "${pr_updated_at_floor}" '
        [
          .[]
          | .workflow_runs[]?
          | select(any(.pull_requests[]?;
              (.number // -1) == $pr_number
              and ($pr_head_sha == "" or (.head.sha // $pr_head_sha) == $pr_head_sha)
            ))
          | select($pr_updated_at_floor == "" or .created_at >= $pr_updated_at_floor)
        ]
        | sort_by(.created_at)
        | last // empty
      '
}

find_missing_images() {
	local ref

	missing_images=()
	for ref in "${image_refs[@]}"; do
		if ! docker manifest inspect "${ref}" >/dev/null 2>&1; then
			missing_images+=("${ref}")
		fi
	done
}

echo "Waiting for fork CI images for PR #${PR_NUMBER}"
echo "Expecting ${#image_refs[@]} image refs with tag ${IMAGE_TAG}"
if [[ -n "${pr_head_sha}" ]]; then
	echo "Matching privileged runs on PR head.sha=${pr_head_sha}"
fi
if [[ -n "${pr_updated_at_floor}" ]]; then
	echo "Ignoring privileged runs created before ${pr_updated_at_floor} (relaxed from PR_UPDATED_AT=${pr_updated_at})"
fi

for attempt in $(seq 1 "${WAIT_ATTEMPTS}"); do
	find_missing_images

	# CI consumers only need the built images; mirror jobs may still be running afterwards.
	if [[ "${#missing_images[@]}" -eq 0 ]]; then
		echo "All required CI images are available."
		exit 0
	fi

	run_json="$(find_matching_run)"

	if [[ -n "${run_json}" && "${run_json}" != "null" ]]; then
		run_id="$(jq -r '.id' <<<"${run_json}")"
		status="$(jq -r '.status' <<<"${run_json}")"
		conclusion="$(jq -r '.conclusion // ""' <<<"${run_json}")"
		url="$(jq -r '.html_url // ""' <<<"${run_json}")"
		created_at="$(jq -r '.created_at // ""' <<<"${run_json}")"
		state="${run_id}:${status}:${conclusion}"

		if [[ "${state}" != "${last_run_state}" || "${run_id}" != "${last_run_id}" ]]; then
			echo "[${attempt}/${WAIT_ATTEMPTS}] Privileged run ${run_id} created_at=${created_at} status=${status} conclusion=${conclusion:-<pending>}"
			if [[ -n "${url}" ]]; then
				echo "Run URL: ${url}"
			fi
			last_run_state="${state}"
			last_run_id="${run_id}"
		fi

		if [[ "${status}" == "completed" && "${conclusion}" != "success" ]]; then
			echo "Privileged run ${run_id} finished with conclusion=${conclusion} before all CI images became available." >&2
			if [[ -n "${url}" ]]; then
				echo "Run URL: ${url}" >&2
			fi
			echo "Still missing (first 10):" >&2
			for ref in "${missing_images[@]:0:10}"; do
				echo " - ${ref}" >&2
			done
			exit 1
		fi
	else
		if [[ "${last_run_state}" != "missing" ]]; then
			echo "[${attempt}/${WAIT_ATTEMPTS}] No matching privileged workflow run found yet."
			last_run_state="missing"
			last_run_id=""
		fi
	fi

	echo "[${attempt}/${WAIT_ATTEMPTS}] Missing ${#missing_images[@]}/${#image_refs[@]} CI images. Waiting ${WAIT_SLEEP_SECONDS}s..."
	echo "Example missing: ${missing_images[0]}"
	sleep "${WAIT_SLEEP_SECONDS}"
done

echo "Timed out waiting for CI images tagged ${IMAGE_TAG}." >&2
echo "Still missing (first 10):" >&2
for ref in "${missing_images[@]:0:10}"; do
	echo " - ${ref}" >&2
done
exit 1
