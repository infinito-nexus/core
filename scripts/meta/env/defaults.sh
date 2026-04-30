#!/usr/bin/env bash
# shellcheck shell=bash
#
# Resolve project default values.

set -euo pipefail

# INFINITO_CONTAINER is fully derived from the current INFINITO_DISTRO. This
# block runs OUTSIDE the load-once guard below so callers that re-export
# INFINITO_DISTRO between matrix iterations (e.g. scripts/tests/deploy/ci/all.sh)
# can re-source defaults.sh and pick up a CONTAINER name in lock-step. Without
# this, the original eager-export only fired on the first source and stuck at
# infinito_nexus_debian even after later iterations exported a different
# INFINITO_DISTRO — see the failure on web-app-wordpress @ fedora in CI run
# 24942172018 / job 73038526513.
: "${INFINITO_DISTRO:=debian}"
: "${INFINITO_RUNNER_PREFIX:=infinito}"
export INFINITO_DISTRO INFINITO_RUNNER_PREFIX
export INFINITO_CONTAINER="${INFINITO_RUNNER_PREFIX}_nexus_${INFINITO_DISTRO}"

if [[ "${INFINITO_ENV_DEFAULTS_LOADED:-}" == "1" ]]; then
	return 0
fi
export INFINITO_ENV_DEFAULTS_LOADED="1"

: "${TEST_DEPLOY_TYPE:=server}"
export TEST_DEPLOY_TYPE

: "${TEST_PATTERN:=test*.py}"
export TEST_PATTERN

: "${DISTROS:=arch debian ubuntu fedora centos}"
export DISTROS
