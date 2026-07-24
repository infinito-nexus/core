#!/usr/bin/env bash
set -euo pipefail

# SPOT: Fail a deploy when its Ansible output carries deprecation warnings, so
# they are caught in CI instead of silently piling up until the feature is
# removed upstream.
#
# Param:
#   $1 = path to the deploy log (the tee'd ansible stdout/stderr)

MARKER='[DEPRECATION WARNING]:'

# Exception: exclude ansible-core 2.20 legacy filter/test PluginLoader deprecation; needs a collection migration, not fixable in role YAML.
FRAMEWORK_NOISE='Instantiating (filter|test) PluginLoader with aliases'

log="${1:?usage: assert_no_deprecation_warnings.sh <deploy-log>}"

if [[ ! -f "${log}" ]]; then
	echo "[ERROR] deprecation check: log not found: ${log}" >&2
	exit 2
fi

if matches="$(grep -nF "${MARKER}" "${log}" | grep -vE "${FRAMEWORK_NOISE}")"; then
	echo "::error::Deploy output contains Ansible deprecation warnings (${MARKER}):" >&2
	printf '%s\n' "${matches}" >&2
	exit 1
fi

echo "deprecation check: no '${MARKER}' entries in ${log}."
