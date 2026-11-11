#!/usr/bin/env bash
# Install all runtime dependencies, incremental via a stamp file.
#
# Re-runs the install chain (dev-python bootstrap -> venv -> python -> ansible)
# only when the content of a recipe input differs from the digest recorded in
# the stamp at build/install.stamp. Content, not mtime: a commit hook that
# rewrites an input unchanged must not invalidate the stamp.
# Pass --force (or run `make install-force`) to drop the stamp first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/python.sh
source "${REPO_ROOT}/scripts/meta/env/python.sh"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_PYTHON_INSTALL_SCRIPT=' "${REPO_ROOT}/default.env")
: "${INFINITO_PYTHON_INSTALL_SCRIPT:?}"

STAMP="build/install.stamp"
DEPS=(
	pyproject.toml
	requirements/requirements.galaxy.yml
	requirements/requirements.git.yml
	scripts/install/python.sh
	scripts/install/ansible.sh
	scripts/install/venv.sh
	"${INFINITO_PYTHON_INSTALL_SCRIPT}"
)

if [[ "${1:-}" == "--force" ]]; then
	rm -f "${STAMP}"
fi

for dep in "${DEPS[@]}"; do
	if [[ ! -f "${dep}" ]]; then
		echo "[install] missing dependency: ${dep}" >&2
		exit 1
	fi
done
digest="$(sha256sum "${DEPS[@]}")"

needs_install=0
if [[ ! -f "${STAMP}" ]]; then
	needs_install=1
elif [[ ! -x "${VENV}/bin/python" ]]; then
	echo "[install] stamp present but venv missing at ${VENV}; reinstalling" >&2
	needs_install=1
elif [[ "$(<"${STAMP}")" != "${digest}" ]]; then
	needs_install=1
fi

if [[ "${needs_install}" -eq 0 ]]; then
	exit 0
fi

bash "${INFINITO_PYTHON_INSTALL_SCRIPT}" ensure
bash scripts/install/venv.sh
bash scripts/install/python.sh deploy
ANSIBLE_COLLECTIONS_DIR="${HOME}/.ansible/collections" bash scripts/install/ansible.sh

stamp_dir="$(dirname "${STAMP}")"
mkdir -p "${stamp_dir}"
chmod 0777 "${stamp_dir}" 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
printf '%s\n' "${digest}" >"${STAMP}"
chmod 0777 "${STAMP}" 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
