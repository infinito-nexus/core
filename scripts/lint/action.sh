#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# TODO: drop the queue ignore once actionlint knows it --
# https://github.com/rhysd/actionlint/issues/654.
actionlint \
	-ignore 'input "client-id" is not defined in action "actions/create-github-app-token' \
	-ignore 'missing input "app-id" which is required by action "actions/create-github-app-token' \
	-ignore 'unexpected key "queue" for "concurrency" section'
