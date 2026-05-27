#!/usr/bin/env bash
set -euo pipefail

: "${PYTHON:?PYTHON not set}"

echo "🔗 Installing pre-commit hooks"
"${PYTHON}" -m pre_commit install
