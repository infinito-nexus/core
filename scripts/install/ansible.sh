#!/usr/bin/env bash
set -euo pipefail

echo "📦 Installing Ansible collections"

: "${PYTHON:?PYTHON not set}"
: "${ANSIBLE_COLLECTIONS_DIR:?ANSIBLE_COLLECTIONS_DIR not set}"

echo "→ Target: ${ANSIBLE_COLLECTIONS_DIR}"
mkdir -p "${ANSIBLE_COLLECTIONS_DIR}"

MAX_ATTEMPTS=5
ATTEMPT=1
INSTALL_TIMEOUT=15m

GALAXY_REQ="requirements/requirements.galaxy.yml"
GIT_REQ="requirements/requirements.git.yml"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -z "${INFINITO_ANSIBLE_COLLECTIONS_SOURCE:-}" ]]; then
	# shellcheck source=/dev/null
	source <(grep -E '^INFINITO_ANSIBLE_COLLECTIONS_SOURCE=' default.env)
fi

: "${INFINITO_ANSIBLE_COLLECTIONS_SOURCE:?not declared in default.env}"

case "${INFINITO_ANSIBLE_COLLECTIONS_SOURCE}" in
galaxy) SOURCE_ORDER=("Galaxy:${GALAXY_REQ}" "Git:${GIT_REQ}") ;;
git) SOURCE_ORDER=("Git:${GIT_REQ}" "Galaxy:${GALAXY_REQ}") ;;
*)
	echo "❌ INFINITO_ANSIBLE_COLLECTIONS_SOURCE must be 'galaxy' or 'git'," \
		"got '${INFINITO_ANSIBLE_COLLECTIONS_SOURCE}'" >&2
	exit 2
	;;
esac

if MISSING="$("${PYTHON}" -m utils.install.collections "${GALAXY_REQ}" "${ANSIBLE_COLLECTIONS_DIR}")"; then
	echo "✅ Every pinned collection is already installed"
	echo "🎉 All collections are ready"
	exit 0
fi
if [ -z "${MISSING}" ]; then
	echo "❌ The collection check exited non-zero without naming a collection," \
		"so it crashed rather than finding work; see its traceback above" >&2
	exit 3
fi
echo "→ Not satisfied yet: ${MISSING}"

installed=0
while ((installed == 0)); do
	echo "▶️  Attempt ${ATTEMPT}/${MAX_ATTEMPTS}"

	for entry in "${SOURCE_ORDER[@]}"; do
		label="${entry%%:*}"
		req="${entry#*:}"

		echo "🌐 Trying ${label} source (${req})…"
		if timeout --foreground "${INSTALL_TIMEOUT}" \
			"${PYTHON}" -m ansible.cli.galaxy collection install \
			-r "${req}" \
			-p "${ANSIBLE_COLLECTIONS_DIR}" \
			--force-with-deps; then

			echo "✅ Collections installed successfully via ${label} on attempt ${ATTEMPT}"
			installed=1
			break
		fi

		echo "⚠️  ${label} install failed on attempt ${ATTEMPT}"
	done

	if ((installed == 1)); then
		break
	fi

	if ((ATTEMPT >= MAX_ATTEMPTS)); then
		echo "❌ Installation failed after ${MAX_ATTEMPTS} attempts."
		echo "   Galaxy and Git fallback both failed."
		exit 1
	fi

	SLEEP_TIME=$((60 + RANDOM % 61))
	echo "⏸️  Attempt ${ATTEMPT} failed for both sources."
	echo "   Waiting ${SLEEP_TIME}s before retry…"

	sleep "${SLEEP_TIME}"
	((ATTEMPT++))
done

echo "🎉 All collections are ready"
