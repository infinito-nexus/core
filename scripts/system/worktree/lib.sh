#!/usr/bin/env bash
# shellcheck shell=bash
#
# Shared helpers for the worktree slot manager. A slot is an integer that
# isolates one checkout from every other: it shifts the compose subnet, the
# host bind IP and the swarm lab subnet, so several worktrees can run their
# stacks side by side. Slot 0 is the primary checkout; every worktree's default
# stack gets the lowest slot the machine slot registry finds free.
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
# Sourced by up.sh, down.sh and prune.sh; not meant to be executed directly.

# up.sh keeps these prefixes as literals because the env lints parse its pins;
# test_lib.py fails when the two drift apart.
WORKTREE_NET_PREFIX=172.30
WORKTREE_LAB_PREFIX=10.160
WORKTREE_MAX_SLOT=254
WORKTREE_SLOTS_MODULE=cli.administration.deploy.development.slots

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

worktree_used_subnets() {
	local -a ids=()
	command -v docker >/dev/null 2>&1 || return 0
	mapfile -t ids < <(docker network ls -q 2>/dev/null)
	[ "${#ids[@]}" -gt 0 ] || return 0
	docker network inspect "${ids[@]}" \
		--format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}' 2>/dev/null || return 0
}

# Returns: prints, one per line, every slot whose compose or swarm lab subnet
#          a docker network holds.
worktree_taken_slots() {
	local subnet octets
	while read -r subnet; do
		case "${subnet}" in
		"${WORKTREE_NET_PREFIX}."*) octets="${subnet#"${WORKTREE_NET_PREFIX}".}" ;;
		"${WORKTREE_LAB_PREFIX}."*) octets="${subnet#"${WORKTREE_LAB_PREFIX}".}" ;;
		*) continue ;;
		esac
		printf '%s\n' "${octets%%.*}"
	done < <(worktree_used_subnets)
}

# Param checkout: an existing checkout of this repository.
# Returns: prints the slot the machine slot registry holds for the checkout's
#          default stack; non-zero when git cannot list the worktrees or the
#          registry refuses.
worktree_allocate_slot() {
	local listing
	local -a known=() taken=()
	listing="$(git worktree list --porcelain)" || return 1
	mapfile -t known < <(awk '/^worktree /{print $2}' <<<"${listing}")
	mapfile -t taken < <(worktree_taken_slots)
	python3 -m "${WORKTREE_SLOTS_MODULE}" allocate "$1" \
		--last "${WORKTREE_MAX_SLOT}" \
		--known ${known[@]+"${known[@]}"} \
		--taken ${taken[@]+"${taken[@]}"}
}

# Param checkout: a removed checkout of this repository.
# Returns: prints every slot the registry held for the checkout's stacks and
#          frees them.
worktree_release_slots() {
	python3 -m "${WORKTREE_SLOTS_MODULE}" release "$1"
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
