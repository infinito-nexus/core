#!/usr/bin/env bash
# External checks for svc-runner: GitHub registration and E2E smoke dispatch.
# Requires RUNNER_API_TOKEN in the environment; skipped silently without it
# (normal in DinD CI where runners cannot register against GitHub).
set -euo pipefail

if [[ -z "${RUNNER_API_TOKEN:-}" ]]; then
    echo "SKIP: RUNNER_API_TOKEN not set — skipping GitHub registration and smoke dispatch"
    exit 0
fi

fail_count=0

# 4) GitHub API: verify at least RUNNER_COUNT runners are registered and online.
echo "Checking GitHub runner registration via API..."
if ! runners_json=$(curl -sf \
    -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/runners"); then
    echo "FAIL: GitHub API unreachable while checking runner registration"
    exit 1
fi
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

# Dispatch test-runner-smoke.yml and wait for success — the real E2E gate
# (runner picks up the job, checks out, reaches Docker via DooD, deploys).
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
        if ! runs_json=$(curl -sf \
            -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/workflows/test-runner-smoke.yml/runs?per_page=10"); then
            echo "FAIL: GitHub API unreachable while polling for smoke run"
            exit 1
        fi
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
            if ! run_json=$(curl -sf \
                -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
                -H "Accept: application/vnd.github+json" \
                "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/runs/${smoke_run_id}"); then
                echo "FAIL: GitHub API unreachable while polling smoke run ${smoke_run_id}"
                exit 1
            fi
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

[[ "${fail_count}" -eq 0 ]] || { echo "FAIL: ${fail_count} external check(s) failed"; exit 1; }
echo "ALL EXTERNAL CHECKS PASSED"
