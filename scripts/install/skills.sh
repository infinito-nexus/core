#!/usr/bin/env bash
# Clone the skills repository (INFINITO_SKILLS_REPOSITORY) and copy its
# skills into this project via the repository's `make project` target.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -z "${INFINITO_SKILLS_REPOSITORY:-}" ]]; then
	# shellcheck source=/dev/null
	source <(grep -hE '^INFINITO_SKILLS_REPOSITORY=' "${REPO_ROOT}/.env" 2>/dev/null)
fi
: "${INFINITO_SKILLS_REPOSITORY:?not set; run 'make dotenv' to generate .env}"

CLONE_DIR="$(mktemp -d /tmp/infinito-skills-install.XXXXXX)"
trap 'rm -rf "${CLONE_DIR}"' EXIT

echo ">>> Installing agent skills from ${INFINITO_SKILLS_REPOSITORY}"
git clone --depth 1 "${INFINITO_SKILLS_REPOSITORY}" "${CLONE_DIR}"
make -C "${CLONE_DIR}" project TARGET="${REPO_ROOT}" # nocheck:make-target

first_party="${REPO_ROOT}/skills"
if [[ -d "${first_party}" ]]; then
	echo ">>> Layering project-local skills from skills/"
	for dst in "${REPO_ROOT}/.agents/skills" "${REPO_ROOT}/.claude/skills"; do
		mkdir -p "${dst}"
		cp -a "${first_party}/." "${dst}/"
	done
fi

echo ">>> Skills installed. Restart your agent to load them."
