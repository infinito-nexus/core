#!/usr/bin/env bash
# Custom deploy test for svc-runner.
# Deploys the Ansible role to localhost and verifies it.
# Runs only on GitHub-hosted ubuntu runners — skipped everywhere else.
set -euo pipefail

if [[ "${INFINITO_DISTRO:-}" != "ubuntu" ]]; then
	echo ">>> svc-runner: skipping distro=${INFINITO_DISTRO:-} (ubuntu only)"
	exit 0
fi

if [[ "${RUNNER_ENVIRONMENT:-}" == "self-hosted" ]]; then
	echo ">>> svc-runner: skipping self-hosted runner (would conflict with production runner)"
	exit 0
fi

OWNER="$(scripts/meta/resolve/repository/owner.sh)"
REPO="${GITHUB_REPOSITORY##*/}"
REPO="${REPO:-infinito-nexus}"

deregister_runner() {
	sudo bash /opt/github-runner/1/svc.sh stop 2>/dev/null || true
	sudo bash /opt/github-runner/1/svc.sh uninstall 2>/dev/null || true
	runner_id=$(gh api "repos/${OWNER}/${REPO}/actions/runners" \
		-q '.runners[] | select(.name | startswith("localhost-")) | .id' \
		2>/dev/null || true)
	if [[ -n "${runner_id}" ]]; then
		gh api --method DELETE "repos/${OWNER}/${REPO}/actions/runners/${runner_id}" || true
		echo ">>> Deregistered runner ID ${runner_id}"
	fi
}
trap deregister_runner EXIT

echo ">>> Installing Ansible"
./scripts/install/apt.sh ansible

echo ">>> Deploying and verifying svc-runner"
RUNNER_COUNT=1 RUNNER_DISTRO=ubuntu OWNER="${OWNER}" REPO="${REPO}" \
	bash scripts/tests/runner.sh
