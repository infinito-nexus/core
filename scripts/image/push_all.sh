#!/usr/bin/env bash
set -euo pipefail

# Argv: <distro> [<distro> ...]  (falls back to INFINITO_DISTROS)

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

distros=("$@")
if ((${#distros[@]} == 0)); then
	: "${INFINITO_DISTROS:?Missing INFINITO_DISTROS and no distro arguments}"
	read -r -a distros <<<"${INFINITO_DISTROS}"
fi

log_dir="${BUILD_LOG_DIR:-${repo_root}/build/image-logs}"
mkdir -p "${log_dir}"

stamp() {
	local distro="$1"
	local line
	while IFS= read -r line; do
		printf '[%s][%(%H:%M:%S)T] %s\n' "${distro}" -1 "${line}"
	done
}

# shellcheck source=scripts/meta/env/load.sh
source "${repo_root}/scripts/meta/env/load.sh"

echo "🏗️  Building ${#distros[@]} image(s) concurrently: ${distros[*]}"
echo "    Logs: ${log_dir}"

gap_prev=1
gap=2

pids=()
started=0
for distro in "${distros[@]}"; do
	if ((started > 0)); then
		sleep "${gap}"
		gap_next=$((gap_prev + gap))
		gap_prev="${gap}"
		gap="${gap_next}"
	fi

	(
		set -o pipefail
		MATRIX_DISTRO="${distro}" bash "${script_dir}/push.sh" 2>&1 |
			stamp "${distro}" |
			tee "${log_dir}/${distro}.log"
	) &
	pids+=("$!")
	started=$((started + 1))
done

failed=()
index=0
for pid in "${pids[@]}"; do
	distro="${distros[${index}]}"
	if wait "${pid}"; then
		echo "✅ ${distro}"
	else
		echo "❌ ${distro}"
		failed+=("${distro}")
	fi
	index=$((index + 1))
done

if ((${#failed[@]} > 0)); then
	echo "❌ Failed distros: ${failed[*]}"
	exit 1
fi

echo "🎉 All ${#distros[@]} image(s) built and pushed"
