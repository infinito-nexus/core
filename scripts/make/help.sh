#!/usr/bin/env bash
# Print Make targets with their descriptions.
#
# Without arguments: short list — one description line per target. The
# description is the topmost comment line in each target's comment block.
#
# With a single argument: print the full comment block for that target —
# the description line plus its schema lines (Usage:, Example:, Note:,
# Param <name>:). See tests/lint/filesystem/makefile/test_single_line_comments.py
# for the canonical schema.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MAKEFILE="${REPO_ROOT}/Makefile"

if [[ ! -f "${MAKEFILE}" ]]; then
	echo "make help: Makefile not found at ${MAKEFILE}" >&2
	exit 1
fi

if [[ -t 1 ]]; then
	C_BOLD=$'\033[1m'
	C_CYAN=$'\033[36m'
	C_GREEN=$'\033[32m'
	C_DIM=$'\033[2m'
	C_RESET=$'\033[0m'
else
	C_BOLD=""
	C_CYAN=""
	C_GREEN=""
	C_DIM=""
	C_RESET=""
fi

# Detail mode: `make help target=<name>` (or positional arg).
if [[ $# -ge 1 && -n "$1" ]]; then
	target="$1"
	awk -v want="${target}" -v g="${C_GREEN}" -v b="${C_BOLD}" -v d="${C_DIM}" -v r="${C_RESET}" '
		/^[[:space:]]*#[[:space:]]*nocheck[[:space:]]*:/ { next }
		/^#/ {
			line = $0
			sub(/^#[[:space:]]?/, "", line)
			block[++n] = line
			next
		}
		/^\.[A-Za-z]/ { next }
		/^[[:space:]]*$/ { n = 0; next }
		/^[A-Za-z][A-Za-z0-9_.-]*:/ && !/:=/ && !/[?+]=/ {
			t = $0
			sub(/:.*$/, "", t)
			if (t == want) {
				printf "%s%s%s\n", b g, t, r
				if (n >= 1) {
					printf "  %s\n", block[1]
					for (i = 2; i <= n; i++) {
						printf "    %s%s%s\n", d, block[i], r
					}
				}
				found = 1
				exit 0
			}
			n = 0
			next
		}
		/^[[:space:]]/ { next }
		{ n = 0 }
		END {
			if (!found) {
				printf "make help: target %s%s%s not found in Makefile\n", b, want, r > "/dev/stderr"
				exit 1
			}
		}
	' "${MAKEFILE}"
	exit $?
fi

printf '\n%sInfinito.Nexus Make targets%s\n' "${C_BOLD}${C_CYAN}" "${C_RESET}"
# shellcheck disable=SC2016 # backticks are literal text in the rendered help banner
printf '%sUsage: make <target> (or `make help target=<target>` for details)%s\n\n' "${C_DIM}" "${C_RESET}"

awk '
	/^[[:space:]]*#[[:space:]]*nocheck[[:space:]]*:/ { next }
	/^#/ {
		line = $0
		sub(/^#[[:space:]]?/, "", line)
		block[++n] = line
		next
	}
	/^\.[A-Za-z]/ { next }
	/^[[:space:]]*$/ { n = 0; next }
	/^[A-Za-z][A-Za-z0-9_.-]*:/ && !/:=/ && !/[?+]=/ {
		target = $0
		sub(/:.*$/, "", target)
		if (!seen[target]++) {
			# The description is the FIRST line of the comment block (top, closest to .PHONY:).
			printf "%s\t%s\n", target, (n >= 1 ? block[1] : "-")
		}
		n = 0
		next
	}
	/^[[:space:]]/ { next }
	{ n = 0 }
' "${MAKEFILE}" |
	sort |
	awk -F'\t' -v g="${C_GREEN}" -v d="${C_DIM}" -v r="${C_RESET}" '
		{ printf "  %s%-32s%s %s%s%s\n", g, $1, r, d, $2, r }
	'

printf '\n'

printf '%sDocumentation:%s %s%s\n\n' "${C_BOLD}" "${C_RESET}" "${C_CYAN}https://docs.infinito.nexus${C_RESET}" ""
