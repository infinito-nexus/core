#!/usr/bin/env bash
# Shut down the stack and reverse all environment changes.
set -euo pipefail

echo "Stopping the compose stack and removing all volumes for a clean teardown."
make compose-down

echo "Reversing the environment bootstrap (DNS, AppArmor, IPv6 settings)."
make environment-teardown
