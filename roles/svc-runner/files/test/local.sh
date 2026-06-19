#!/usr/bin/env bash
# Local checks for svc-runner: container health, runner process, and DooD.
# In DinD mode the entrypoint sleeps (no GitHub token to register with GitHub).
# Structural checks always run; the full deploy test runs in CI only (requires
# GITHUB_TOKEN and a ci-<sha> image tag so the runner can pull from GHCR).
set -euo pipefail

fail_count=0

# --- DinD: entrypoint sleeps; verify containers + DooD + full deploy in CI ---
if [[ "${DOCKER_IN_CONTAINER}" == "true" ]]; then
    echo "DinD mode: verifying runner containers started..."
    for i in $(seq 1 "${RUNNER_COUNT}"); do
        # || echo "not found": container inspect exits non-zero when container
        # does not exist; without this set -e would kill the script before
        # fail_count can be incremented.
        state=$(container inspect --format '{{.State.Status}}' "${RUNNER_PROJECT_PREFIX}-${i}" 2>/dev/null || echo "not found")
        if [[ "${state}" != "running" ]]; then
            echo "FAIL: ${RUNNER_PROJECT_PREFIX}-${i} is not running (state=${state})"
            fail_count=$((fail_count + 1))
        else
            echo "OK: ${RUNNER_PROJECT_PREFIX}-${i} is running"
        fi
    done
    [[ "${fail_count}" -eq 0 ]] || { echo "FAIL: ${fail_count} container(s) not healthy in DinD"; exit 1; }

    # Verify DooD socket is reachable — core capability for running CI jobs.
    echo "DinD mode: verifying DooD socket in ${RUNNER_PROJECT_PREFIX}-1..."
    if ! docker exec "${RUNNER_PROJECT_PREFIX}-1" docker version >/dev/null 2>&1; then
        echo "FAIL: Docker socket not accessible inside ${RUNNER_PROJECT_PREFIX}-1 — DooD broken in DinD"
        exit 1
    fi
    echo "OK: DooD socket accessible inside ${RUNNER_PROJECT_PREFIX}-1"

    # Full deploy test — mirrors test-runner-smoke.yml but runs inside runner-1
    # using DooD into the DinD daemon instead of the host Docker socket.
    # Skipped locally: GITHUB_TOKEN is absent and INFINITO_IMAGE_TAG=latest
    # (no ci-<sha> image exists outside of CI).
    if [[ -n "${GITHUB_TOKEN:-}" ]] && [[ "${INFINITO_IMAGE_TAG:-}" == ci-* ]]; then
        echo "DinD mode: running full deploy test inside ${RUNNER_PROJECT_PREFIX}-1..."

        # Run from a per-instance copy, not the shared /opt/src/infinito (the
        # outer runner's .env/Corefile there would make inner coredns serve the
        # wrong IP). Same-path dir keeps DooD bind-mounts valid.
        _iso_src="${RUNNER_INSTALL_DIR}/1/nested-src"
        container exec --user root "${RUNNER_PROJECT_PREFIX}-1" \
            bash -c "rm -rf ${_iso_src} && mkdir -p ${_iso_src} && tar -C /opt/src/infinito --exclude='./.env' --exclude='./compose/coredns/Corefile' --exclude='./.venvs' --exclude='./venv' --exclude='*/node_modules' --exclude='*/__pycache__' -cf - . | tar -C ${_iso_src} -xf - && chown -R github-runner:github-runner ${_iso_src}"

        # Authenticate to GHCR so runner-1 can pull the infinito CI image via DooD.
        # docker login runs INSIDE runner-1 (no container wrapper there); <<< avoids
        # the pipe pattern that would trigger the raw-docker lint rule.
        container exec -e "GITHUB_TOKEN=${GITHUB_TOKEN}" "${RUNNER_PROJECT_PREFIX}-1" \
            bash -c "docker login ghcr.io -u github-actions --password-stdin <<< \"\${GITHUB_TOKEN}\""

        # Install Ansible and Python dependencies (same as a real CI job would do).
        container exec "${RUNNER_PROJECT_PREFIX}-1" \
            bash -c "cd ${_iso_src} && make install"

        # Start from clean nested state, like a fresh CI run. /etc/nginx is a
        # named volume (svc-prx-openresty meta/volumes.yml); a prior run can
        # leave nginx.conf there as a directory, breaking the openresty
        # bootstrap. Remove the nested project's containers + volumes first.
        container exec "${RUNNER_PROJECT_PREFIX}-1" \
            bash -c "docker ps -aq --filter label=com.docker.compose.project=infinito | xargs -r docker rm -f" \
            || true
        container exec "${RUNNER_PROJECT_PREFIX}-1" \
            bash -c "docker volume ls -q --filter name=^infinito_ | xargs -r docker volume rm" \
            || true

        # Deploy web-app-dashboard exactly as the smoke test does.
        # DooD routes Docker commands to the DinD daemon, so the infinito
        # container and web-app-dashboard containers are created inside DinD —
        # the same topology as production, one Docker level down.
        #
        # Override COMPOSE_PROJECT_NAME / INFINITO_RUNNER_PREFIX: runner-1's
        # own env_file sets both to "runner-1". Without overriding, the nested
        # infinito stack would inherit that project name and try to reuse the
        # pre-existing "runner-1_default" network (auto-subnet, created by the
        # runner's own compose project) — its subnet does not contain the
        # 172.30.0.0/24 static IPs the infinito stack assigns, so attach fails
        # with "no configured subnet contains IP address". Pinning to
        # "infinito" makes the nested stack create its own isolated,
        # correctly-subnetted "infinito_default" network, matching normal CI.
        # RUNTIME=github runs the E2E roles (test-e2e-cli + test-e2e-playwright)
        # like a real CI deploy; the required_by guard expects test-e2e-cli to
        # execute. Confined to this nested deploy.
        container exec \
            -e "COMPOSE_PROJECT_NAME=infinito" \
            -e "INFINITO_RUNNER_PREFIX=infinito" \
            -e "RUNTIME=github" \
            -e "apps=web-app-dashboard" \
            -e "disable=matomo" \
            -e "INFINITO_DEPLOY_TYPE=server" \
            -e "INFINITO_DISTROS=debian" \
            -e "INFINITO_INVENTORY_DIR=/tmp/runner-dind-inventory" \
            -e "INFINITO_DOCKER_VOLUME=/tmp/runner-dind-docker" \
            -e "INFINITO_IMAGE_TAG=${INFINITO_IMAGE_TAG}" \
            -e "INFINITO_GHCR_MIRROR_PREFIX=${INFINITO_GHCR_MIRROR_PREFIX:-}" \
            -e "GITHUB_TOKEN=${GITHUB_TOKEN}" \
            -e "GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-}" \
            -e "GITHUB_REPOSITORY_OWNER=${GITHUB_REPOSITORY_OWNER:-}" \
            -e "ANSIBLE_LOG_PATH=/tmp/ansible-runner-dind-test.log" \
            "${RUNNER_PROJECT_PREFIX}-1" \
            bash "${_iso_src}/scripts/tests/deploy/ci/all.sh"

        echo "OK: full deploy inside ${RUNNER_PROJECT_PREFIX}-1 succeeded"
    else
        echo "DinD mode: skipping full deploy test (GITHUB_TOKEN absent or INFINITO_IMAGE_TAG is not ci-<sha>)"
    fi

    echo "ALL LOCAL CHECKS PASSED (DinD)"
    exit 0
fi

# --- Real host: container health + runner process + DooD ---
echo "Verifying containers, runner process, and Docker socket access..."
for i in $(seq 1 "${RUNNER_COUNT}"); do
    container="${RUNNER_PROJECT_PREFIX}-${i}"

    # 1) Container is running
    state=$(container inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || echo "not found")
    if [[ "${state}" != "running" ]]; then
        echo "FAIL: ${container} is not running (state=${state})"
        fail_count=$((fail_count + 1))
        continue
    fi
    echo "OK: ${container} is running"

    # 2) Runner process is alive inside the container
    if ! docker exec "${container}" pgrep -f "run.sh" >/dev/null 2>&1; then
        echo "FAIL: run.sh not found inside ${container} — runner may have crashed after registration"
        fail_count=$((fail_count + 1))
    else
        echo "OK: ${container} has active runner process"
    fi

    # 3) Docker socket reachable from inside the container (DooD).
    # Proves the runner can actually execute CI job steps that use Docker.
    if ! docker exec "${container}" docker version >/dev/null 2>&1; then
        echo "FAIL: Docker socket not accessible from inside ${container} — DooD broken; runner cannot run CI jobs"
        fail_count=$((fail_count + 1))
    else
        echo "OK: ${container} can reach Docker socket (DooD works)"
    fi
done

[[ "${fail_count}" -eq 0 ]] || { echo "FAIL: ${fail_count} local check(s) failed"; exit 1; }
echo "ALL LOCAL CHECKS PASSED"
