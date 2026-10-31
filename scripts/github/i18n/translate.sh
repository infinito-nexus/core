#!/usr/bin/env bash
# Param: $1 - ISO 639-1 code of the language this runner translates
set -euo pipefail

code="${1:?Usage: translate.sh <ISO 639-1 code>}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"
for domain in core docs; do
	python3 -m cli.build.i18n translate --domain "${domain}" --languages "${code}"
done
