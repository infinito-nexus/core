#!/usr/bin/env bash
# Install the general terminal aliases from INFINITO_ALIAS_REPOSITORY, then
# layer this project's Infinito.Nexus-specific aliases on top so both are
# sourced by the shell.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SHELL_CONFIG_DIR="${HOME}/.config/shell"
ALIASES_TARGET="${SHELL_CONFIG_DIR}/aliases-infinito"

if [[ -z "${INFINITO_ALIAS_REPOSITORY:-}" ]]; then
	# shellcheck source=/dev/null
	source <(grep -hE '^INFINITO_ALIAS_REPOSITORY=' "${REPO_ROOT}/.env" 2>/dev/null)
fi
: "${INFINITO_ALIAS_REPOSITORY:?not set; run 'make dotenv' to generate .env}"

CLONE_DIR="$(mktemp -d /tmp/infinito-alias-install.XXXXXX)"
trap 'rm -rf "${CLONE_DIR}"' EXIT

echo ">>> Installing general terminal aliases from ${INFINITO_ALIAS_REPOSITORY}"
git clone --depth 1 "${INFINITO_ALIAS_REPOSITORY}" "${CLONE_DIR}"
make -C "${CLONE_DIR}" install

echo ">>> Installing Infinito.Nexus-specific aliases"
mkdir -p "${SHELL_CONFIG_DIR}"
cp "${REPO_ROOT}/aliases" "${ALIASES_TARGET}"

source_line='[ -f ~/.config/shell/aliases-infinito ] && . ~/.config/shell/aliases-infinito'
for rc in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
	touch "${rc}"
	grep -qxF "${source_line}" "${rc}" || printf '%s\n' "${source_line}" >>"${rc}"
done

echo ">>> Aliases installed. Open a new shell or 'source ~/.bashrc' (or ~/.zshrc) to activate them."
