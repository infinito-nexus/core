#!/usr/bin/env bash
# Multiply timeouts in Ansible task files and Docker compose templates
# for slow CI hardware (e.g. self-hosted SATA-RAID runners).
#
# Reads env vars (SPOT defined in scripts/meta/env/github.sh):
#   INFINITO_TIMEOUT_MULTIPLIER  > 1: apply; <= 1: no-op.
#   INFINITO_REPO_ROOT           path to the repository root inside the container.
#
# Changes (ephemeral — actions/checkout resets them on the next job):
#   • Ansible task retries      → retries × multiplier
#   • Docker healthcheck start_period → start_period × multiplier
#
# Example: multiplier=30, retries=60, delay=2s → 60×30×2s = 3600s = 1 h
# Fast hardware finishes early; slow hardware waits as long as needed up to 1 h.
set -euo pipefail

MULTIPLIER="${INFINITO_TIMEOUT_MULTIPLIER}"
REPO_ROOT="${INFINITO_REPO_ROOT}"

if [[ "${MULTIPLIER}" -le 1 ]]; then
	exit 0
fi

echo ">>> Applying ${MULTIPLIER}x timeout multiplier (self-hosted hardware)"

# Ansible task retries → retries × MULTIPLIER
find "${REPO_ROOT}/roles" -path "*/tasks/*.yml" -name "*.yml" -print0 |
	xargs -0 -r perl -i -pe "s/^(\s+retries:\s+)(\d+)/\$1.(\$2*${MULTIPLIER})/e"

# Docker compose healthcheck start_period → start_period × MULTIPLIER
find "${REPO_ROOT}/roles" \( -name "*.yml" -o -name "*.yml.j2" \) \
	-not -path "*/tasks/*" -print0 |
	xargs -0 -r perl -i -pe "s/^(\s+start_period:\s+)(\d+)s/\$1.(\$2*${MULTIPLIER}).'s'/e"

echo ">>> Done"
