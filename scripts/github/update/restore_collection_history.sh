#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"
: "${HISTORY_PATH:?Missing HISTORY_PATH}"
: "${HISTORY_WORKFLOW:?Missing HISTORY_WORKFLOW}"

ARTIFACT_NAME="${ARTIFACT_NAME:-collection-source-history}"

mkdir -p "$(dirname "${HISTORY_PATH}")"

run_id="$(
	gh run list \
		--repo "${GITHUB_REPOSITORY}" \
		--workflow "${HISTORY_WORKFLOW}" \
		--status success \
		--limit 1 \
		--json databaseId \
		--jq '.[0].databaseId // empty'
)"

if [[ -z "${run_id}" ]]; then
	echo "No previous successful run; starting a fresh history."
	exit 0
fi

tmp_dir="$(mktemp -d)"
if ! gh run download "${run_id}" \
	--repo "${GITHUB_REPOSITORY}" \
	--name "${ARTIFACT_NAME}" \
	--dir "${tmp_dir}"; then
	echo "Run ${run_id} carries no ${ARTIFACT_NAME}; starting a fresh history."
	exit 0
fi

cp "${tmp_dir}/$(basename "${HISTORY_PATH}")" "${HISTORY_PATH}"
echo "Restored history from run ${run_id}."
