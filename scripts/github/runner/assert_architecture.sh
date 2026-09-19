#!/usr/bin/env bash
# Env:
#   INFINITO_ARCHITECTURE  the architecture the matrix assigned (required)
set -euo pipefail

: "${INFINITO_ARCHITECTURE:?Missing INFINITO_ARCHITECTURE}"

PROBE_IMAGE="alpine:3"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"

actual="$("${repo_root}/scripts/meta/resolve/architecture.sh")"

if [[ "${actual}" == "${INFINITO_ARCHITECTURE}" ]]; then
	echo "🏗️ ${actual} runs natively here (uname -m: $(uname -m))"
	exit 0
fi

if [[ -n "${GITHUB_ACTIONS:-}" && -z "${ACT:-}" ]]; then
	echo "❌ architecture mismatch: the matrix assigned '${INFINITO_ARCHITECTURE}', the runner is '${actual}' (uname -m: $(uname -m))." >&2
	echo "   The runner label for '${INFINITO_ARCHITECTURE}' no longer resolves to that hardware; fix RUNNERS in utils/github/variant/pools.py." >&2
	exit 1
fi

if ! docker run --rm --platform "linux/${INFINITO_ARCHITECTURE}" "${PROBE_IMAGE}" true >/dev/null 2>&1; then
	echo "❌ the matrix assigned '${INFINITO_ARCHITECTURE}' and this '${actual}' host cannot execute it." >&2
	echo "   Register the emulation, then re-run:" >&2
	echo "     sudo systemctl restart systemd-binfmt.service" >&2
	echo "     docker run --privileged --rm tonistiigi/binfmt --install ${INFINITO_ARCHITECTURE}" >&2
	exit 1
fi

echo "🏗️ ${INFINITO_ARCHITECTURE} runs emulated on this ${actual} host"
