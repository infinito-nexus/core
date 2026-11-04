#!/usr/bin/env bash
# Clone the skills repository (INFINITO_SKILLS_REPOSITORY) at INFINITO_SKILLS_REF
# and install its skills into every checkout INFINITO_SKILLS_TARGETS names via
# the repository's `make project` target, then layer this checkout's
# agents/skills/ on top of each.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

for key in INFINITO_SKILLS_REPOSITORY INFINITO_SKILLS_REF INFINITO_SKILLS_TARGETS; do
	if [[ -z "${!key:-}" ]]; then
		# shellcheck source=/dev/null
		source <(grep -hE "^${key}=" "${REPO_ROOT}/.env" 2>/dev/null)
	fi
done
: "${INFINITO_SKILLS_REPOSITORY:?not set; run 'make dotenv' to generate .env}"
: "${INFINITO_SKILLS_REF:?not set; run 'make dotenv' to generate .env}"
: "${INFINITO_SKILLS_TARGETS:?not set; run 'make dotenv' to generate .env}"

main_checkout() {
	git -C "${REPO_ROOT}" worktree list --porcelain |
		awk '/^worktree / && !found { print substr($0, 10); found = 1 }'
}

declare -A seen=()
targets=()
read -ra names <<<"${INFINITO_SKILLS_TARGETS}"
for name in "${names[@]}"; do
	case "${name}" in
	worktree) dir="${REPO_ROOT}" ;;
	main) dir="$(cd "$(main_checkout)" && pwd -P)" ;;
	*)
		echo "INFINITO_SKILLS_TARGETS: unknown target '${name}'; expected worktree or main" >&2
		exit 2
		;;
	esac
	if [[ -z "${seen[${dir}]:-}" ]]; then
		seen["${dir}"]=1
		targets+=("${dir}")
	fi
done
if ((${#targets[@]} == 0)); then
	echo "INFINITO_SKILLS_TARGETS names no target; expected worktree and/or main" >&2
	exit 2
fi

CLONE_DIR="$(mktemp -d /tmp/infinito-skills-install.XXXXXX)"
trap 'rm -rf "${CLONE_DIR}"' EXIT

echo ">>> Fetching agent skills from ${INFINITO_SKILLS_REPOSITORY} at ${INFINITO_SKILLS_REF}"
if git ls-remote --exit-code "${INFINITO_SKILLS_REPOSITORY}" "refs/heads/${INFINITO_SKILLS_REF}" "refs/tags/${INFINITO_SKILLS_REF}" >/dev/null; then
	git clone --quiet --depth 1 --branch "${INFINITO_SKILLS_REF}" "${INFINITO_SKILLS_REPOSITORY}" "${CLONE_DIR}"
else
	git clone --quiet --no-checkout "${INFINITO_SKILLS_REPOSITORY}" "${CLONE_DIR}"
	git -C "${CLONE_DIR}" checkout --quiet --detach "${INFINITO_SKILLS_REF}^{commit}"
fi

first_party="${REPO_ROOT}/agents/skills"
for target in "${targets[@]}"; do
	echo ">>> Installing agent skills into ${target}"
	make -C "${CLONE_DIR}" project TARGET="${target}" # nocheck:make-target
	if [[ -d "${first_party}" ]]; then
		echo ">>> Layering project-local skills from ${first_party}"
		for dst in "${target}/.agents/skills" "${target}/.claude/skills"; do
			mkdir -p "${dst}"
			cp -a "${first_party}/." "${dst}/"
		done
	fi
done

echo ">>> Skills installed. Restart your agent to load them."
