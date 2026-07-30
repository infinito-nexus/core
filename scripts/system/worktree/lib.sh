#!/usr/bin/env bash
# shellcheck shell=bash
#
# Shared helpers for the worktree slot manager. A slot is an integer that
# isolates one checkout from every other: it shifts the compose subnet, the
# host bind IP and the swarm lab subnet, so several worktrees can run their
# stacks side by side. Slot 0 is the primary checkout and owns the shared
# cache stack; every worktree gets the next free slot and joins that cache
# over an external docker network.
#
# Volumes are deliberately not slotted: compose already namespaces them by
# project, and INFINITO_DOCKER_VOLUME names a top-level compose key, so
# renaming it would point the mount at an undeclared volume.
#
# The pins are written to custom.env AND passed to the generator in a cleared
# environment: custom.env keeps them reproducible across later `make dotenv`
# runs, while the explicit env covers branches whose generator predates
# custom.env support. Inheriting the caller's environment would leak the
# invoking worktree's own slot into the new one.
#
# Slot discovery reads custom.env first: a branch whose default.env predates
# INFINITO_INSTANCE never materialises the key into .env, which would make the
# checkout look like slot 0 and hand its number out twice.
#
# Sourced by up.sh and down.sh; not meant to be executed directly.

worktree_slug() {
	printf '%s' "$1" | sed -e 's#[^a-zA-Z0-9._-]#-#g' -e 's#^[^a-zA-Z0-9]*##' -e 's#[-.]*$##'
}

worktree_default_base() {
	local url
	url="$(git remote get-url origin)"
	url="${url%.git}"
	url="${url#*://}"
	url="${url#*@}"
	printf '%s/.local/share/worktrees/%s/%s' "${HOME}" "${url%%[:/]*}" "${url#*[:/]}"
}

worktree_path() {
	printf '%s/%s' "$2" "$1"
}

worktree_slot_of() {
	local slot=0 file
	for file in "$1/custom.env" "$1/.env"; do
		if [ -f "${file}" ]; then
			slot="$(awk -F= '/^INFINITO_INSTANCE=/{print $2}' "${file}" | tail -n1)"
			if [ -n "${slot}" ]; then
				break
			fi
		fi
	done
	case "${slot}" in
	'' | *[!0-9]*) slot=0 ;;
	esac
	printf '%s' "${slot}"
}

worktree_next_slot() {
	local max=0 path slot
	while read -r path; do
		slot="$(worktree_slot_of "${path}")"
		if [ "${slot}" -gt "${max}" ]; then
			max="${slot}"
		fi
	done < <(git worktree list --porcelain | awk '/^worktree /{print $2}')
	printf '%s' "$((max + 1))"
}

worktree_cache_network() {
	docker inspect infinito-registry-cache \
		--format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' 2>/dev/null |
		head -n1
}
