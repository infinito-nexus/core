#!/usr/bin/env bash
# Splits a JSON array of app IDs proportionally between GitHub-hosted and
# self-hosted CI runners.
#
# When CI_SELF_HOSTED_RUNNER_COUNT is 0 or unset, all apps are assigned to
# the GitHub-hosted batch and the self-hosted batch is empty — CI behaves
# exactly as before with no self-hosted runners registered.
#
# The split ratio mirrors the relative throughput of each runner pool:
#   github_count = floor(total × GITHUB_QUOTA / (GITHUB_QUOTA + SELF_HOSTED_COUNT))
#
# Apps listed in PINNED_GITHUB are always kept on GitHub-hosted runners
# regardless of the split ratio (e.g. svc-runner installs host-level systemd
# services that conflict with production self-hosted runners).
#
# Inputs (environment variables):
#   APPS_JSON                    JSON array of app IDs from the discover step
#   CI_SELF_HOSTED_RUNNER_COUNT  self-hosted runner instance count (default: 0)
#
# Outputs (appended to $GITHUB_OUTPUT):
#   apps_github       JSON array routed to GitHub-hosted runners
#   apps_self_hosted  JSON array routed to self-hosted runners ([] when disabled)
set -euo pipefail

APPS_JSON="${APPS_JSON:-[]}"
SELF_HOSTED_COUNT="${CI_SELF_HOSTED_RUNNER_COUNT:-0}"
GITHUB_QUOTA=20

# Apps that must always run on GitHub-hosted runners.
PINNED_GITHUB='["svc-runner"]'

if [[ "${SELF_HOSTED_COUNT}" -le 0 ]]; then
	echo "apps_github=${APPS_JSON}" >>"${GITHUB_OUTPUT}"
	echo "apps_self_hosted=[]" >>"${GITHUB_OUTPUT}"
	total="$(echo "${APPS_JSON}" | jq 'length')"
	echo "=== Runner split: all ${total} apps → GitHub-hosted (self-hosted disabled) ==="
	exit 0
fi

# Separate pinned apps from the pool before splitting.
pinned="$(echo "${APPS_JSON}" | jq -c --argjson pins "${PINNED_GITHUB}" '[.[] | select(. as $a | $pins | index($a) != null)]')"
pool="$(echo "${APPS_JSON}" | jq -c --argjson pins "${PINNED_GITHUB}" '[.[] | select(. as $a | $pins | index($a) == null)]')"

total="$(echo "${pool}" | jq 'length')"
github_count=$((total * GITHUB_QUOTA / (GITHUB_QUOTA + SELF_HOSTED_COUNT)))
self_count=$((total - github_count))

apps_github="$(echo "${pool}" | jq -c --argjson pinned "${pinned}" "\$pinned + .[0:${github_count}]")"
apps_self="$(echo "${pool}" | jq -c ".[${github_count}:]")"

echo "apps_github=${apps_github}" >>"${GITHUB_OUTPUT}"
echo "apps_self_hosted=${apps_self}" >>"${GITHUB_OUTPUT}"

pinned_count="$(echo "${pinned}" | jq 'length')"
echo "=== Runner split: ${pinned_count} pinned + ${github_count} apps → GitHub-hosted, ${self_count} apps → self-hosted (${SELF_HOSTED_COUNT} runners) ==="
