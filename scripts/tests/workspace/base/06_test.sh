#!/usr/bin/env bash
# Run the full validation suite before deploying.
set -euo pipefail

echo "Running the combined validation suite: lint, unit tests, and integration tests."
make test
