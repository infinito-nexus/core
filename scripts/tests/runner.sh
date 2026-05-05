#!/usr/bin/env bash
# Deploys the svc-runner Ansible role to localhost and runs the verification suite.
# Requires: gh CLI authenticated (GH_TOKEN env var), ansible-playbook in PATH.
set -euo pipefail

RUNNER_COUNT="${RUNNER_COUNT:-1}"
RUNNER_DISTRO="${RUNNER_DISTRO:-ubuntu}"
OWNER="$(scripts/meta/resolve/repository/owner.sh)"
REPO="${REPO:-infinito-nexus}"

TMPDIR_RUNNER="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_RUNNER}"' EXIT

cat >"${TMPDIR_RUNNER}/inventory.ini" <<'EOF'
[runners]
localhost ansible_connection=local
EOF

cat >"${TMPDIR_RUNNER}/playbook.yml" <<'EOF'
---
- hosts: runners
  become: true
  roles:
    - svc-runner
EOF

echo ">>> Deploying svc-runner to localhost (distro=${RUNNER_DISTRO}, count=${RUNNER_COUNT}, owner=${OWNER}, repo=${REPO})"
ansible-playbook \
	-i "${TMPDIR_RUNNER}/inventory.ini" \
	"${TMPDIR_RUNNER}/playbook.yml" \
	-e "runner_distribution=${RUNNER_DISTRO}" \
	-e "runner_count=${RUNNER_COUNT}" \
	-e "runner_github_owner=${OWNER}" \
	-e "runner_github_repo=${REPO}" \
	-e "MASK_CREDENTIALS_IN_LOGS=true"

echo ">>> Running svc-runner verification suite"
RUNNER_COUNT="${RUNNER_COUNT}" bash roles/svc-runner/files/test.sh
