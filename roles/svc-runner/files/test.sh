#!/usr/bin/env bash
# E2E verification for svc-runner.
# Checks: binary presence, container health, Docker socket access from inside each
# container (DooD — proves runner can execute CI jobs), GitHub registration, and
# dispatches test-runner-smoke.yml to verify a real end-to-end CI job runs to success.
# Variables sourced from test.env.j2 by test-e2e-cli. RUNNER_API_TOKEN from env only.
set -euo pipefail

: "${DOCKER_IN_CONTAINER:?}"
: "${RUNNER_COUNT:?}"
: "${RUNNER_GIT_REF:?}"
: "${RUNNER_GITHUB_OWNER:?}"
: "${RUNNER_GITHUB_REPO:?}"
: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_PROJECT_PREFIX:?}"
: "${RUNNER_USER:?}"

echo "OK: env vars verified (RUNNER_COUNT=${RUNNER_COUNT}, RUNNER_PROJECT_PREFIX=${RUNNER_PROJECT_PREFIX}, RUNNER_GIT_REF=${RUNNER_GIT_REF})"

# --- Binary check (skip gracefully if svc-runner was not deployed in this run) ---
if [[ ! -f "${RUNNER_INSTALL_DIR}/1/run.sh" ]]; then
    echo "SKIP: svc-runner not deployed in this run (binary absent at ${RUNNER_INSTALL_DIR}/1/run.sh)"
    exit 0
fi
echo "OK: runner binary present at ${RUNNER_INSTALL_DIR}/1/run.sh"

fail_count=0

# --- DinD: registration and Docker socket are skipped (entrypoint sleeps); only verify containers started ---
if [[ "${DOCKER_IN_CONTAINER}" == "true" ]]; then
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
    echo "ALL CHECKS PASSED (DinD)"
    exit 0
fi

# --- Real host: container health + DooD + GitHub registration + E2E smoke dispatch ---
echo "Real-host mode: verifying containers, Docker socket access, GitHub registration, and dispatching E2E smoke..."

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

# 4) GitHub API: verify at least RUNNER_COUNT runners are registered and online.
# RUNNER_API_TOKEN is a secret — must come from the caller's environment, not test.env.
if [[ -z "${RUNNER_API_TOKEN:-}" ]]; then
    echo "SKIP: RUNNER_API_TOKEN not set — skipping GitHub registration and smoke dispatch"
    [[ "${fail_count}" -eq 0 ]] || { echo "FAIL: ${fail_count} check(s) failed"; exit 1; }
    echo "ALL CHECKS PASSED (no API token)"
    exit 0
fi

echo "Checking GitHub runner registration via API..."
runners_json=$(curl -sf \
    -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/runners" \
    || echo "{}")
online_count=$(echo "${runners_json}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(sum(1 for r in data.get('runners', []) if r.get('status') == 'online'))
" 2>/dev/null || echo "0")
if [[ "${online_count}" -lt "${RUNNER_COUNT}" ]]; then
    echo "FAIL: expected at least ${RUNNER_COUNT} online runner(s) on GitHub, found ${online_count}"
    fail_count=$((fail_count + 1))
else
    echo "OK: ${online_count} runner(s) online on GitHub (${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO})"
fi

# 5) Dispatch test-runner-smoke.yml and wait for success.
# This is the real E2E gate: a runner picks up the job, checks out the repo,
# accesses Docker via DooD, and runs a full Ansible deploy (web-app-dashboard).
echo "Dispatching test-runner-smoke.yml against ref=${RUNNER_GIT_REF}..."
dispatch_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

dispatch_http=$(curl -sf -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/workflows/test-runner-smoke.yml/dispatches" \
    -d "{\"ref\":\"${RUNNER_GIT_REF}\"}" \
    || echo "000")

if [[ "${dispatch_http}" != "204" ]]; then
    echo "FAIL: smoke workflow dispatch returned HTTP ${dispatch_http} (expected 204)"
    fail_count=$((fail_count + 1))
else
    echo "OK: smoke workflow dispatched (HTTP 204)"

    # Discover the run ID — GitHub creates it asynchronously; retry for up to 60s.
    smoke_run_id=""
    attempts=0
    while [[ -z "${smoke_run_id}" && "${attempts}" -lt 12 ]]; do
        sleep 5
        runs_json=$(curl -sf \
            -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/workflows/test-runner-smoke.yml/runs?per_page=10" \
            || echo "{}")
        smoke_run_id=$(echo "${runs_json}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
dispatch_time = '${dispatch_time}'
runs = [r for r in data.get('workflow_runs', []) if r.get('created_at', '') >= dispatch_time]
print(runs[0]['id'] if runs else '')
" 2>/dev/null || echo "")
        attempts=$((attempts + 1))
    done

    if [[ -z "${smoke_run_id}" ]]; then
        echo "FAIL: could not find smoke run after dispatch (waited $((attempts * 5))s)"
        fail_count=$((fail_count + 1))
    else
        echo "OK: smoke run found (id=${smoke_run_id}), polling for completion (timeout=90min)..."

        # Poll until completed or 90-minute timeout.
        deadline=$(($(date +%s) + 5400))
        smoke_conclusion=""
        while [[ "$(date +%s)" -lt "${deadline}" ]]; do
            sleep 30
            run_json=$(curl -sf \
                -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
                -H "Accept: application/vnd.github+json" \
                "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/runs/${smoke_run_id}" \
                || echo "{}")
            smoke_status=$(echo "${run_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
            smoke_conclusion=$(echo "${run_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('conclusion','') or '')" 2>/dev/null || echo "")
            echo "  smoke run ${smoke_run_id}: status=${smoke_status} conclusion=${smoke_conclusion}"
            if [[ "${smoke_status}" == "completed" ]]; then
                break
            fi
        done

        if [[ "${smoke_conclusion}" == "success" ]]; then
            echo "OK: smoke deploy succeeded — runner executed a real CI job end-to-end"
        else
            echo "FAIL: smoke deploy conclusion=${smoke_conclusion:-timeout/unknown} (expected success)"
            fail_count=$((fail_count + 1))
        fi
    fi
fi

if [[ "${fail_count}" -gt 0 ]]; then
    echo "FAIL: ${fail_count} check(s) failed"
    exit 1
fi

echo "ALL CHECKS PASSED"
