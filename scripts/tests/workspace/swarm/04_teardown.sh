#!/usr/bin/env bash
# Shut down the stack and reverse all environment changes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/../utils/teardown.sh"
