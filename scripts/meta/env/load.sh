#!/usr/bin/env bash
# shellcheck shell=bash
#
# Sources `.env` (auto-generates via `python -m cli.meta.env` if missing)
# with setdefault semantics: caller-set values win over `.env` defaults.
# Idempotent (INFINITO_ENV_LOADED). INFINITO_ENV_GENERATING short-circuits
# re-entry from generator subshells (BASH_ENV would otherwise recurse).

_infinito_env_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
_infinito_env_dotenv="${_infinito_env_repo_root}/.env"

# Re-resolve PYTHON + PATH on every source so a venv created mid-chain takes over.
# shellcheck source=scripts/meta/env/python.sh
source "${_infinito_env_repo_root}/scripts/meta/env/python.sh"

if [[ -n "${VENV:-}" && -d "${VENV%/}/bin" ]]; then
	case ":${PATH:-}:" in
	*:"${VENV%/}/bin":*) ;;
	*) export PATH="${VENV%/}/bin${PATH:+:${PATH}}" ;;
	esac
fi

if [[ "${INFINITO_ENV_LOADED:-}" == "1" ]]; then # nocheck: env-loader-internal-guard
	unset _infinito_env_repo_root _infinito_env_dotenv
	return 0
fi
if [[ "${INFINITO_ENV_GENERATING:-}" == "1" ]]; then # nocheck: env-loader-internal-guard
	unset _infinito_env_repo_root _infinito_env_dotenv
	return 0
fi

if [[ ! -f "${_infinito_env_dotenv}" ]]; then
	(
		cd "${_infinito_env_repo_root}" || exit 1
		export INFINITO_ENV_GENERATING=1
		"${PYTHON}" -m cli.meta.env
	) >&2
fi

# Snapshot caller-set values, restore them after the bulk source (setdefault).
declare -A _infinito_env_preserved=()
while IFS= read -r _infinito_env_line; do
	case "${_infinito_env_line}" in
	"" | "#"*) continue ;;
	esac
	_infinito_env_key="${_infinito_env_line%%=*}"
	if [[ "${_infinito_env_key}" == "${_infinito_env_line}" ]]; then
		continue
	fi
	if [[ -n "${!_infinito_env_key:-}" ]]; then
		_infinito_env_preserved["${_infinito_env_key}"]="${!_infinito_env_key}"
	fi
done <"${_infinito_env_dotenv}"
unset _infinito_env_line _infinito_env_key

set -a
# shellcheck disable=SC1090
source "${_infinito_env_dotenv}"
set +a

for _infinito_env_key in "${!_infinito_env_preserved[@]}"; do
	declare -gx "${_infinito_env_key}=${_infinito_env_preserved[${_infinito_env_key}]}"
done
unset _infinito_env_key _infinito_env_preserved

export INFINITO_ENV_LOADED="1"
unset _infinito_env_repo_root _infinito_env_dotenv
