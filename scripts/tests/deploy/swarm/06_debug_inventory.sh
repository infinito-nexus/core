#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/tests/deploy/swarm/00_topology.sh
. "$(dirname "$0")/00_topology.sh"

export ANSIBLE_HOST_KEY_CHECKING=False
ansible-inventory -i /tmp/inv/devices.yml --graph
echo '---'
ansible -i /tmp/inv/devices.yml --vault-password-file /tmp/inv/.password \
	"${MGR}" -m debug -a "msg={{ group_names }}" || true
