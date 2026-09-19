#!/usr/bin/env bash
# Env:
#   INFINITO_ARCHITECTURE  the architecture the matrix assigned (required)
set -euo pipefail

: "${INFINITO_ARCHITECTURE:?Missing INFINITO_ARCHITECTURE}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"

actual="$("${repo_root}/scripts/meta/resolve/architecture.sh")"

if [[ "${actual}" != "${INFINITO_ARCHITECTURE}" ]]; then
	echo "❌ architecture mismatch: the matrix assigned '${INFINITO_ARCHITECTURE}', the runner is '${actual}' (uname -m: $(uname -m))." >&2
	echo "   The runner label for '${INFINITO_ARCHITECTURE}' no longer resolves to that hardware; fix RUNNERS in utils/github/variant/pools.py." >&2
	exit 1
fi

echo "🏗️ ${actual} runner confirmed (uname -m: $(uname -m))"
