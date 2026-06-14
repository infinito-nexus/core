#!/usr/bin/env bash
set -euo pipefail

export ANSIBLE_HOST_KEY_CHECKING=False
ansible-inventory -i /tmp/inv/devices.yml --graph
echo '---'
ansible -i /tmp/inv/devices.yml --vault-password-file /tmp/inv/.password \
	swarm-mgr-01 -m debug -a "msg={{ group_names }}" || true
