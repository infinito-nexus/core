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
# Sourced by up.sh, down.sh and prune.sh; not meant to be executed directly.

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

WORKTREE_MAX_SLOT=254
WORKTREE_NET_PREFIX=172.30
WORKTREE_LAB_PREFIX=10.160

worktree_used_subnets() {
	local -a ids=()
	command -v docker >/dev/null 2>&1 || return 0
	mapfile -t ids < <(docker network ls -q 2>/dev/null)
	[ "${#ids[@]}" -gt 0 ] || return 0
	docker network inspect "${ids[@]}" \
		--format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}' 2>/dev/null || return 0
}

# Param slot: the candidate slot.
# Param subnets: newline-separated subnets docker networks already hold.
# Returns: 0 when a network holds the slot's compose or swarm lab subnet.
worktree_slot_taken() {
	local subnet
	while read -r subnet; do
		case "${subnet}" in
		"${WORKTREE_NET_PREFIX}.$1."* | "${WORKTREE_LAB_PREFIX}.$1."*) return 0 ;;
		esac
	done <<<"$2"
	return 1
}

worktree_next_slot() {
	local used=" " path slot subnets
	while read -r path; do
		used+="$(worktree_slot_of "${path}") "
	done < <(git worktree list --porcelain | awk '/^worktree /{print $2}')
	subnets="$(worktree_used_subnets)"
	for ((slot = 1; slot <= WORKTREE_MAX_SLOT; slot++)); do
		case "${used}" in
		*" ${slot} "*) continue ;;
		esac
		if ! worktree_slot_taken "${slot}" "${subnets}"; then
			printf '%s' "${slot}"
			return 0
		fi
	done
	printf '%s' "$((WORKTREE_MAX_SLOT + 1))"
}

worktree_meta_dir() {
	sed -n 's/^gitdir: //p' "$1/.git" 2>/dev/null
}

# Param entry: a .git/worktrees/<id> directory.
# Returns: 0 fully removed, 1 unregistered but the directory is pinned,
#          2 still registered.
worktree_unregister() {
	local entry="$1"
	rm -f "${entry}/gitdir" "${entry}/HEAD" 2>/dev/null
	if [ -e "${entry}/gitdir" ] || [ -e "${entry}/HEAD" ]; then
		return 2
	fi
	rm -rf "${entry}" 2>/dev/null || return 1
	return 0
}

worktree_report_held() {
	[ "$#" -gt 0 ] || return 0
	echo ">>> Unregistered, but the sandbox pins these metadata dirs; git ignores them now:"
	printf '      %s\n' "$@"
	echo ">>> Clear them outside the sandbox: rm -rf $*"
}

worktree_cache_network() {
	docker inspect infinito-registry-cache \
		--format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' 2>/dev/null |
		head -n1
}
