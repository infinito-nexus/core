#!/usr/bin/env bash
# shellcheck shell=bash
#
# Resolve GitHub/Act specific overrides.

set -euo pipefail

if [[ "${INFINITO_ENV_GITHUB_LOADED:-}" == "1" ]]; then
	return 0
fi
export INFINITO_ENV_GITHUB_LOADED="1"

: "${RUNNING_ON_GITHUB:=false}"

if [[ "${RUNNING_ON_GITHUB}" == "true" ]]; then
	: "${INFINITO_PULL_POLICY:=always}"
	: "${INFINITO_IMAGE_TAG:=latest}"

	# SPOT: canonical GHCR namespace owner used by image and mirrors resolution.
	_owner="${GITHUB_REPOSITORY_OWNER:-${OWNER:-}}"
	if [[ -z "${_owner}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
		_owner="${GITHUB_REPOSITORY%%/*}"
	fi
	_owner="${_owner,,}"
	if [[ -z "${_owner}" ]]; then
		echo "ERROR: GITHUB_REPOSITORY_OWNER (or GITHUB_REPOSITORY/OWNER) must be set when RUNNING_ON_GITHUB=true" >&2
		return 1
	fi
	export GITHUB_REPOSITORY_OWNER="${_owner}"

	_repo_name="${INFINITO_IMAGE_REPOSITORY:-}"
	if [[ -z "${_repo_name}" ]]; then
		_repo_name="$(scripts/meta/resolve/repository/name.sh)"
	fi
	_repo_name="${_repo_name,,}"
	export INFINITO_IMAGE_REPOSITORY="${_repo_name}"

	: "${INFINITO_IMAGE:=ghcr.io/${_owner}/${_repo_name}/${INFINITO_DISTRO}:${INFINITO_IMAGE_TAG}}"
	# SPOT: default GHCR mirror prefix used by development mirror resolution.
	: "${INFINITO_GHCR_MIRROR_PREFIX:=mirror}"

	: "${INFINITO_NO_BUILD:=1}"
	: "${INFINITO_DOCKER_VOLUME:=/mnt/docker}"
	: "${INFINITO_DOCKER_MOUNT:=/var/lib/docker}"
	: "${INFINITO_COMPILE:=0}"

	export INFINITO_PULL_POLICY INFINITO_IMAGE_TAG INFINITO_IMAGE
	export INFINITO_GHCR_MIRROR_PREFIX INFINITO_NO_BUILD
	export INFINITO_DOCKER_VOLUME INFINITO_DOCKER_MOUNT
	export INFINITO_COMPILE
else
	: "${INFINITO_COMPILE:=1}"
	export INFINITO_COMPILE
fi

if [[ -n "${NIX_CONFIG:-}" ]]; then
	export NIX_CONFIG
fi

: "${INFINITO_RUNNER_PREFIX:=infinito}"
: "${INFINITO_PRESERVE_DOCKER_CACHE:=false}"
: "${INFINITO_TIMEOUT_MULTIPLIER:=1}"
: "${INFINITO_REPO_ROOT:=/opt/src/infinito}"
export INFINITO_RUNNER_PREFIX INFINITO_PRESERVE_DOCKER_CACHE INFINITO_TIMEOUT_MULTIPLIER INFINITO_REPO_ROOT
