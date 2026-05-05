#!/usr/bin/env bash
set -euo pipefail

# SPOT: Deploy exactly ONE app across all distros (serial).
#
# Additionally:
# - Track duration per distro
# - Enforce a global time budget for the whole run (env: MAX_TOTAL_SECONDS)
# - Skip a distro if remaining time is smaller than the max duration of any previous distro run
#
# Required env:
#   APPS="web-app-keycloak"
#   TEST_DEPLOY_TYPE="server|workstation|universal"
#   DISTROS="arch debian ubuntu fedora centos"
#   INVENTORY_DIR="/path/to/inventory"
#
# Optional env:
#   PYTHON="python3"
#   MAX_TOTAL_SECONDS="5400"   # override the script default of 19800 seconds
#
# Script-local defaults preserved from the old Make wrapper:
#   MISSING_ONLY=true
#   MAX_TOTAL_SECONDS=19800

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/all.sh" ]]; then
	# shellcheck source=scripts/meta/env/all.sh
	source "scripts/meta/env/all.sh"
else
	echo "[ERROR] Missing env file: scripts/meta/env/all.sh" >&2
	exit 2
fi

: "${APPS:?APPS is required (e.g. APPS=web-app-keycloak)}"
: "${TEST_DEPLOY_TYPE:?TEST_DEPLOY_TYPE is required (server|workstation|universal)}"
: "${DISTROS:?DISTROS is required (e.g. 'arch debian ubuntu fedora centos')}"
: "${INVENTORY_DIR:?INVENTORY_DIR is required}"

case "${TEST_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "[ERROR] Invalid TEST_DEPLOY_TYPE: ${TEST_DEPLOY_TYPE}" >&2
	exit 2
	;;
esac

: "${PYTHON:=python3}"
: "${MISSING_ONLY:=true}"
if [[ -z "${MAX_TOTAL_SECONDS+x}" ]]; then
	MAX_TOTAL_SECONDS=19800
fi

export INVENTORY_DIR MISSING_ONLY MAX_TOTAL_SECONDS

if [[ -n "${MAX_TOTAL_SECONDS}" ]]; then
	if ! [[ "${MAX_TOTAL_SECONDS}" =~ ^[0-9]+$ ]]; then
		echo "[ERROR] MAX_TOTAL_SECONDS must be an integer (seconds), got: '${MAX_TOTAL_SECONDS}'" >&2
		exit 2
	fi
fi

read -r -a distro_arr <<<"${DISTROS}"
mapfile -t distro_arr < <(printf '%s\n' "${distro_arr[@]}" | shuf)
echo "=== Distro execution order: ${distro_arr[*]} ==="

global_start="$(date +%s)"
deadline=""
if [[ -n "${MAX_TOTAL_SECONDS}" ]]; then
	deadline="$((global_start + MAX_TOTAL_SECONDS))"
	echo "=== Global time budget enabled: ${MAX_TOTAL_SECONDS}s (deadline epoch=${deadline}) ==="
else
	echo "=== Global time budget disabled (MAX_TOTAL_SECONDS was set empty) ==="
fi

max_seen=0
skipped=0
ran=0
failed=0
durations=() # store "distro=seconds" lines

sync_ci_image_for_run() {
	local owner tag repo_name

	if [[ -n "${OWNER:-}" || -n "${GITHUB_REPOSITORY_OWNER:-}" || -n "${GITHUB_REPOSITORY:-}" ]]; then
		owner="$(OWNER="${OWNER:-}" GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" scripts/meta/resolve/repository/owner.sh)"
	else
		owner=""
	fi
	tag="${INFINITO_IMAGE_TAG:-latest}"
	repo_name="${INFINITO_IMAGE_REPOSITORY:-}"

	# Keep local/dev workflows untouched; only adjust image when CI owner context exists.
	if [[ -z "${owner}" ]]; then
		return 0
	fi

	if [[ -z "${repo_name}" ]]; then
		repo_name="$(scripts/meta/resolve/repository/name.sh)"
	fi

	export INFINITO_IMAGE="ghcr.io/${owner}/${repo_name}/${INFINITO_DISTRO}:${tag}"
	echo ">>> CI image synced: ${INFINITO_IMAGE}"
}

echo ">>> Installing CI dependencies"
"${PYTHON}" -m pip install ruamel.yaml PyYAML

for distro in "${distro_arr[@]}"; do
	now="$(date +%s)"
	remaining=""

	if [[ -n "${deadline}" ]]; then
		remaining="$((deadline - now))"

		if ((remaining <= 0)); then
			echo "[WARN] Global budget exhausted (remaining=${remaining}s). Stopping further distro runs."
			break
		fi

		# Skip logic: only if we already have a max_seen from a prior run
		if ((max_seen > 0 && remaining < max_seen)); then
			echo "[WARN] Skipping distro=${distro}: remaining=${remaining}s < max_seen=${max_seen}s (fast-fail heuristic)"
			skipped=$((skipped + 1))
			continue
		fi
	fi

	echo "=== Running dedicated distro deploy: distro=${distro} app=${APPS} type=${TEST_DEPLOY_TYPE} ==="
	if [[ -n "${remaining}" ]]; then
		echo ">>> Time budget: remaining=${remaining}s max_seen=${max_seen}s"
	fi

	export INFINITO_DISTRO="${distro}"
	# Re-source defaults.sh so its always-derived INFINITO_CONTAINER block
	# (outside the load-once guard) refreshes from the current INFINITO_DISTRO.
	# This is the single spot that owns the derivation; consumers below
	# (dedicated.sh, python deploy → entity.sh) just inherit the env.
	source "scripts/meta/env/defaults.sh"
	sync_ci_image_for_run

	distro_start="$(date +%s)"

	set +e
	if [[ -f "scripts/tests/deploy/ci/custom/${APPS}.sh" ]]; then
		bash "scripts/tests/deploy/ci/custom/${APPS}.sh"
	else
		scripts/tests/deploy/ci/dedicated.sh \
			--apps "${APPS}"
	fi
	rc=$?
	set -e

	distro_end="$(date +%s)"
	dur="$((distro_end - distro_start))"
	durations+=("${distro}=${dur}s")
	ran=$((ran + 1))

	if ((dur > max_seen)); then
		max_seen="$dur"
	fi

	echo ">>> Duration: distro=${distro} took ${dur}s (max_seen=${max_seen}s)"

	if [[ $rc -ne 0 ]]; then
		echo "[ERROR] Deploy failed for distro=${distro} app=${APPS} (rc=${rc})" >&2
		failed=$((failed + 1))
		exit "$rc"
	fi
done

global_end="$(date +%s)"
total="$((global_end - global_start))"

echo
echo "=== Summary ==="
echo "app=${APPS} type=${TEST_DEPLOY_TYPE}"
echo "ran=${ran} skipped=${skipped} failed=${failed}"
echo "total_runtime=${total}s max_seen_duration=${max_seen}s"
if [[ -n "${deadline}" ]]; then
	now="$(date +%s)"
	remaining="$((deadline - now))"
	echo "budget=${MAX_TOTAL_SECONDS}s remaining=${remaining}s"
fi
echo "per-distro:"
for line in "${durations[@]}"; do
	echo "  - ${line}"
done
