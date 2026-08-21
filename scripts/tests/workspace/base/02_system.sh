#!/usr/bin/env bash
# Show disk usage and purge cached state before building.
set -euo pipefail

echo "Showing current disk and Docker resource usage before purging."
make diagnose-disk-usage

echo "Freeing disk and memory on minimal-hardware systems before the build."
make system-purge
