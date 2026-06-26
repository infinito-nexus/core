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

# Build the infinito image locally and deploy web-app-dashboard in a sealed
# throwaway dockerd (host stack untouched). No GitHub/GHCR.
_iso_src="${RUNNER_INSTALL_DIR}/1/nested-src"
echo "DinD mode: running full local deploy test inside ${RUNNER_PROJECT_PREFIX}-1..."
# container cp the repo into runner-1 (no compose mount — keeps test wiring here),
# then isolate a per-instance copy (drop .env/Corefile so inner coredns serves the right IP).
container exec --user root "${RUNNER_PROJECT_PREFIX}-1" mkdir -p /opt/src/infinito
container cp /opt/src/infinito/. "${RUNNER_PROJECT_PREFIX}-1:/opt/src/infinito"
container exec --user root "${RUNNER_PROJECT_PREFIX}-1" \
    bash -c "rm -rf ${_iso_src} && mkdir -p ${_iso_src} && tar -C /opt/src/infinito --exclude='./.env' --exclude='./compose/coredns/Corefile' --exclude='./.venvs' --exclude='./venv' --exclude='*/node_modules' --exclude='*/__pycache__' -cf - . | tar -C ${_iso_src} -xf - && chown -R github-runner:github-runner ${_iso_src}"
container exec "${RUNNER_PROJECT_PREFIX}-1" bash -c "cd ${_iso_src} && make install"

# shellcheck disable=SC2016  # inner $VARs run in the sandbox shell; outer values spliced via '"..."'
if ! container exec "${RUNNER_PROJECT_PREFIX}-1" bash -c '
    set -euo pipefail
    cd "'"${_iso_src}"'"
    INFINITO_DISTRO=debian make build
    img="$(INFINITO_DISTRO=debian bash scripts/meta/resolve/image/local.sh)"

    # Throwaway sealed dockerd (runner-1 netns); repo mounted at the same path for
    # the infinito compose bind-mount; torn down on exit.
    SB="runner-dind-sandbox"
    docker rm -f "$SB" >/dev/null 2>&1 || true
    trap '"'"'docker rm -f "$SB" >/dev/null 2>&1 || true'"'"' EXIT
    docker run -d --privileged --name "$SB" \
        --network "container:'"${RUNNER_PROJECT_PREFIX}"'-1" \
        -v "'"${_iso_src}"'":"'"${_iso_src}"'" \
        -e DOCKER_TLS_CERTDIR= docker:dind --host=tcp://0.0.0.0:2375 >/dev/null
    export DOCKER_HOST=tcp://127.0.0.1:2375
    ready=0
    for _ in $(seq 1 40); do
        if docker version >/dev/null 2>&1; then ready=1; break; fi
        sleep 2
    done
    [ "$ready" = 1 ] || { echo "FAIL: sealed dind daemon did not come up"; exit 1; }

    # Deploy the loaded local image (no build/pull); owner/repo cleared so all.sh
    # never swaps in a GHCR image.
    DOCKER_HOST= docker save "$img" | docker load
    COMPOSE_PROJECT_NAME=infinito INFINITO_RUNNER_PREFIX=infinito \
    RUNTIME=github CI=true apps=web-app-dashboard \
    disable=matomo,sso,asset,simpleicons,logout \
    INFINITO_DEPLOY_TYPE=server INFINITO_DISTROS=debian \
    INFINITO_IMAGE="$img" INFINITO_BUILD=0 INFINITO_PULL_POLICY=never \
    GITHUB_REPOSITORY_OWNER= GITHUB_REPOSITORY= \
    INFINITO_INVENTORY_DIR=/tmp/runner-dind-inventory \
    INFINITO_DOCKER_VOLUME=/tmp/runner-dind-docker \
    ANSIBLE_LOG_PATH=/tmp/ansible-runner-dind-test.log \
    bash scripts/tests/deploy/ci/all.sh
'; then
    echo "FAIL: local full deploy failed"
    exit 1
fi
echo "OK: local full deploy succeeded (sealed sandbox, no GitHub)"

echo "ALL LOCAL CHECKS PASSED (DinD)"
