#!/usr/bin/env bash
# Entrypoint for the ephemeral GitHub Actions runner container.
# On every start: register with GitHub (ephemeral), run one job, exit.
# Docker restarts the container and the cycle repeats.
set -euo pipefail

if [[ "${DOCKER_IN_CONTAINER:-false}" == "true" ]]; then
    echo "SKIP: DinD environment — skipping GitHub registration"
    if [[ -f "./run.sh" ]]; then
        echo "OK: runner binary present at $(pwd)/run.sh"
    else
        echo "FAIL: run.sh not found"
        exit 1
    fi
    exec sleep infinity
fi

rm -rf ./_work 2>/dev/null || true
find /tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

: "${RUNNER_API_TOKEN:?RUNNER_API_TOKEN must be set}"
: "${RUNNER_GITHUB_OWNER:?RUNNER_GITHUB_OWNER must be set}"
: "${RUNNER_GITHUB_REPO:?RUNNER_GITHUB_REPO must be set}"
: "${RUNNER_NAME:?RUNNER_NAME must be set}"
: "${RUNNER_LABELS:?RUNNER_LABELS must be set}"

TOKEN=$(curl --connect-timeout 5 --max-time 60 -fsSL \
    -X POST \
    -H "Authorization: Bearer ${RUNNER_API_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}/actions/runners/registration-token" \
    | jq -r .token)

./config.sh \
    --url "https://github.com/${RUNNER_GITHUB_OWNER}/${RUNNER_GITHUB_REPO}" \
    --token "${TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --ephemeral \
    --unattended \
    --replace

exec ./run.sh
