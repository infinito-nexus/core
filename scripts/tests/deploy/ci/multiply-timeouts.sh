#!/usr/bin/env bash
# Multiply timeouts in Ansible task files and Docker compose templates
# for slow CI hardware (e.g. self-hosted SATA-RAID runners).
#
# Usage: multiply-timeouts.sh <multiplier> [repo-root]
#   <multiplier> > 1: apply; <= 1: no-op.
#
# Changes (ephemeral — actions/checkout resets them on the next job):
#   • Ansible task retries      → retries × multiplier
#   • Docker healthcheck start_period → start_period × multiplier
#
# Example: multiplier=30, retries=60, delay=2s → 60×30×2s = 3600s = 1 h
# Fast hardware finishes early; slow hardware waits as long as needed up to 1 h.
set -euo pipefail

MULTIPLIER="${1:-1}"
# Resolve repo root via the dedicated deploy CLI (realpath → baked-in container path).
# Falls back to /opt/src/infinito when run outside the container.
REPO_ROOT="${2:-$(python3 -c 'from cli.deploy.dedicated.paths import REPO_ROOT; print(REPO_ROOT)' 2>/dev/null || echo '/opt/src/infinito')}"

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
