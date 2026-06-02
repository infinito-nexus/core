#!/usr/bin/env bash
set -euo pipefail

pip install --no-cache-dir --break-system-packages -e .
ansible-galaxy collection install community.docker ansible.posix

PYTHON=python3 bash scripts/setup.sh
