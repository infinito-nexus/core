#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"
codes="$(python3 -m cli.build.i18n languages)"
echo "Machine-translatable languages: ${codes}"
echo "codes=${codes}" >>"${GITHUB_OUTPUT}"
