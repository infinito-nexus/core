#!/usr/bin/env bash
# shellcheck shell=bash
#
# Validate every Mermaid diagram in the repository's Markdown by rendering it
# with @mermaid-js/mermaid-cli (mmdc). A diagram GitHub cannot render (syntax
# error, reserved-word node id, ...) makes mmdc exit nonzero, failing the lint.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

if ! command -v mmdc >/dev/null 2>&1; then
	echo "mmdc (@mermaid-js/mermaid-cli) not installed. Run 'make install-lint' first." >&2
	exit 127
fi

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

puppeteer_cfg="${workdir}/puppeteer-config.json"
printf '%s\n' '{"args":["--no-sandbox","--disable-gpu"]}' >"${puppeteer_cfg}"

mapfile -t md_files < <(grep -rlF --include='*.md' '```mermaid' . 2>/dev/null | sort || true)

if [[ ${#md_files[@]} -eq 0 ]]; then
	echo "No Markdown files contain a mermaid block; nothing to render."
	exit 0
fi

printf '%s\n' 'flowchart LR' '  a --> b' >"${workdir}/preflight.mmd"
if ! mmdc --puppeteerConfigFile "${puppeteer_cfg}" -i "${workdir}/preflight.mmd" \
	-o "${workdir}/preflight.svg" >"${workdir}/preflight.log" 2>&1; then
	printf "mmdc cannot render a minimal diagram, so none of the %d Markdown file(s) was checked. 'make install-lint-force' provisions its browser:\n" \
		"${#md_files[@]}" >&2
	sed 's/^/    /' "${workdir}/preflight.log" >&2
	exit 1
fi

: "${INFINITO_WORKER_CPU:?INFINITO_WORKER_CPU must be set (provided by default.env via the env loader)}"
jobs="${INFINITO_WORKER_CPU}"

# shellcheck disable=SC2329,SC2317  # invoked indirectly through xargs + bash -c
render_one() {
	local md="$1"
	local slug
	slug="$(printf '%s' "${md}" | tr '/.' '__')"
	if ! mmdc --puppeteerConfigFile "${puppeteer_cfg}" -i "${md}" \
		-o "${workdir}/${slug}.out.md" >"${workdir}/${slug}.log" 2>&1; then
		printf '%s\n' "${md}" >"${workdir}/${slug}.fail"
	fi
}
export -f render_one
export workdir puppeteer_cfg

# shellcheck disable=SC2016  # the single-quoted body expands inside the child bash
printf '%s\n' "${md_files[@]}" |
	xargs -P "${jobs}" -I {} bash -c 'render_one "$1"' _ {}

status=0
for fail in "${workdir}"/*.fail; do
	[[ -e "${fail}" ]] || continue
	status=1
	md="$(cat "${fail}")"
	printf '❌ %s\n' "${md}"
	sed 's/^/    /' "${fail%.fail}.log"
done

if [[ "${status}" -eq 0 ]]; then
	printf '✅ %d Markdown file(s) with mermaid render cleanly.\n' "${#md_files[@]}"
fi

exit "${status}"
