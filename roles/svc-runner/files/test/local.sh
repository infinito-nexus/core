#!/usr/bin/env bash
# nocheck: raw-docker  # drives a throwaway dind sandbox; the container/compose wrappers aren't available there
# svc-runner checks: container health, DooD socket, and (sync pass only) a full
# nested web-app-dashboard deploy in a sealed throwaway dockerd. No GitHub/GHCR.
set -euo pipefail

fail_count=0

echo "DinD mode: verifying runner containers started..."
for i in $(seq 1 "${RUNNER_COUNT}"); do
    state=$(container inspect --format '{{.State.Status}}' "${RUNNER_PROJECT_PREFIX}-${i}" 2>/dev/null || echo "not found")
    if [[ "${state}" != "running" ]]; then
        echo "FAIL: ${RUNNER_PROJECT_PREFIX}-${i} is not running (state=${state})"
        fail_count=$((fail_count + 1))
    else
        echo "OK: ${RUNNER_PROJECT_PREFIX}-${i} is running"
    fi
done
[[ "${fail_count}" -eq 0 ]] || { echo "FAIL: ${fail_count} container(s) not healthy in DinD"; exit 1; }

echo "DinD mode: verifying DooD socket in ${RUNNER_PROJECT_PREFIX}-1..."
if ! docker exec "${RUNNER_PROJECT_PREFIX}-1" docker version >/dev/null 2>&1; then
    echo "FAIL: Docker socket not accessible inside ${RUNNER_PROJECT_PREFIX}-1 — DooD broken in DinD"
    exit 1
fi
echo "OK: DooD socket accessible inside ${RUNNER_PROJECT_PREFIX}-1"

# The full deploy is identical across the sync/async passes; run it once (sync).
if [[ "${ASYNC_ENABLED:-false}" == "true" ]]; then
    echo "Skipping full deploy on async pass (validated on sync pass)"
    echo "ALL LOCAL CHECKS PASSED (DinD)"
    exit 0
fi

# Full reinstall deploy of the dashboard inside ephemeral runner-1. No GitHub/GHCR.
_iso_src="${RUNNER_INSTALL_DIR}/1/nested-src"
echo "DinD mode: running full reinstall deploy inside ${RUNNER_PROJECT_PREFIX}-1..."
# container cp the repo into runner-1 (no compose mount — keeps test wiring here),
# then isolate a per-instance copy (drop .env/Corefile so inner coredns serves the right IP).
container exec --user root "${RUNNER_PROJECT_PREFIX}-1" mkdir -p /opt/src/infinito
container cp /opt/src/infinito/. "${RUNNER_PROJECT_PREFIX}-1:/opt/src/infinito"
container exec --user root "${RUNNER_PROJECT_PREFIX}-1" \
    bash -c "rm -rf ${_iso_src} && mkdir -p ${_iso_src} && tar -C /opt/src/infinito --exclude='./.env' --exclude='./compose/coredns/Corefile' --exclude='./.venvs' --exclude='./venv' --exclude='*/node_modules' --exclude='*/__pycache__' -cf - . | tar -C ${_iso_src} -xf - && chown -R github-runner:github-runner ${_iso_src}"
container exec "${RUNNER_PROJECT_PREFIX}-1" bash -c "cd ${_iso_src} && make install"

# shellcheck disable=SC2016  # inner $VARs run in runner-1's shell; outer values spliced via '"..."'
if ! container exec "${RUNNER_PROJECT_PREFIX}-1" bash -c '
    set -euo pipefail
    cd "'"${_iso_src}"'"
    INFINITO_DISTRO=debian make build
    img="$(INFINITO_DISTRO=debian bash scripts/meta/resolve/image/local.sh)"

    # dev stack uses fuse-overlayfs (raw docker:dind falls back to vfs → disk full).
    # disable= all group_names-guarded services; cdn/javascript stay (hard deps).
    INFINITO_DISTRO=debian INFINITO_DISTROS=debian \
    INFINITO_INVENTORY_DIR=/tmp/runner-dind-inventory \
    INFINITO_IMAGE="$img" INFINITO_BUILD=0 INFINITO_PULL_POLICY=never \
    make compose-deploy mode=reinstall type=server \
        apps=web-app-dashboard \
        disable=matomo,sso,asset,simpleicons,logout,css,prometheus
'; then
    echo "FAIL: local full reinstall deploy failed"
    exit 1
fi
echo "OK: local full reinstall deploy succeeded (dev stack, no GitHub)"

echo "ALL LOCAL CHECKS PASSED (DinD)"
