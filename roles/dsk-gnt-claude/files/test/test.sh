#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

claude --version
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${here}/shared/gateway/run.sh"
