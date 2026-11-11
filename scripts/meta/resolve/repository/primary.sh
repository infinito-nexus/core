#!/usr/bin/env bash
# Print the primary checkout of the repository at $PWD: the first entry of
# `git worktree list`, the same path from every worktree of the repository.
set -euo pipefail

git worktree list --porcelain | awk '/^worktree / && !found { print substr($0, 10); found = 1 }'
