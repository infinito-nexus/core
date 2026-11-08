#!/usr/bin/env bash
# Param: $1 cgroup v2 mount root (/sys/fs/cgroup)
# Param: $2 proc mount root (/proc)
# Param: $3 library root holding the electron[<N>]/electron binaries Code - OSS runs on (/usr/lib)
set -uo pipefail
shopt -s nullglob extglob

readonly cgroups="$1" proc="$2" library="$3"
readonly shield=-900
rg_tids=()

# oom_score_adj is inherited at fork: ptyHost and the extension host run the same binary
# but fork the user's shells and builds, so only the main process (renamed to code-oss
# by /usr/lib/code/code.mjs) and the renderers may hold the shield. Zygote-forked
# renderers rewrite their argv into one space-joined title, so --type= is matched in both forms.
# An editor started before an electron upgrade runs a replaced inode whose exe link ends
# in " (deleted)", so the path is compared, not the inode.
is_editor() {
	local pid="$1" exe comm
	exe="$(readlink -- "${proc}/${pid}/exe" 2>/dev/null)" || return 1
	[[ "${exe% (deleted)}" == "${library}"/electron*([0-9])/electron ]] || return 1
	read -r comm 2>/dev/null <"${proc}/${pid}/comm" || return 1
	[[ "${comm}" == code-oss ]] && return 0
	grep -qzE -- '(^| )--type=renderer( |$)' "${proc}/${pid}/cmdline" 2>/dev/null
}

for procs in "${cgroups}"/user.slice/user-*.slice/user@*.service/app.slice/app-*code*oss-*.scope/cgroup.procs; do
	while read -r pid; do
		read -r current 2>/dev/null <"${proc}/${pid}/oom_score_adj" || continue
		if is_editor "${pid}"; then
			target="${shield}"
		elif ((current < 0)); then
			target=0
		else
			target="${current}"
		fi
		[[ "${current}" == "${target}" ]] || echo "${target}" 2>/dev/null >"${proc}/${pid}/oom_score_adj"
		read -r comm 2>/dev/null <"${proc}/${pid}/comm" || continue
		[[ "${comm}" == rg ]] || continue
		for task in "${proc}/${pid}/task/"*; do
			rg_tids+=("${task##*/}")
		done
	done <"${procs}"
done

if ((${#rg_tids[@]})); then
	renice -n 19 -p "${rg_tids[@]}" >/dev/null 2>&1
	ionice -c 3 -t -p "${rg_tids[@]}" >/dev/null 2>&1
fi
exit 0
