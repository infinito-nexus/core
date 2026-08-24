#!/usr/bin/env bash
# Build the local Docker image and verify a clean no-cache build.
set -euo pipefail

echo "Building the local image using the Docker layer cache."
make build

echo "Rebuilding the local image from scratch to verify the build without cache reuse."
make build-no-cache
