#!/usr/bin/env bash
# Enlarge host swap on a GitHub-hosted runner. Replaces the runner's
# default ~4 GB swap with a fixed-size swapfile so transient memory
# spikes (e.g. peertube plugin install, issue #162) don't trip the host
# OOM-killer, WITHOUT starving the rest of the job of disk space.
#
# Uses / when containerd already lives on /mnt (relocate_docker_dataroot.sh
# runs first), otherwise prefers /mnt when it is a separate partition (classic ubuntu-latest
# layout with /dev/sdb mounted at /mnt). On current public runners
# there is no separate /mnt partition — everything lives on /, so we
# place the swapfile there. The swap size is a hard constant, never a
# "free minus buffer" computation: a previous version consumed ~99 GB
# on a 145 GB root, leaving so little headroom that later Docker layer
# writes (Playwright test image pull) failed with ENOSPC. See #162.
#
# A zram device comes first: compressed swap in RAM gives the same swap size
# without the swapfile's blocks on the runner's one disk, which a heavy swarm
# HA row needs for its images. The swapfile below stays the fallback when the
# runner's kernel offers no zram module.
#
# Usage: enlarge_swap.sh [size-gb]
# Default: 16 GB (empirically sufficient for the peertube spike).
#
# Debug toggle: set SKIP_SWAP=1 to leave the runner's default swap
# untouched (A/B probe for issues caused by this script itself).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP="${HERE}/dump_state.sh"

if [ "${SKIP_SWAP:-0}" = "1" ]; then
	echo "SKIP_SWAP=1 — leaving default runner swap in place."
	"$DUMP" "skip-swap (SKIP_SWAP=1)"
	exit 0
fi

SWAP_GB="${1:-16}"
MIN_FREE_GB=$((SWAP_GB + 4)) # need the target size plus a little slack

"$DUMP" "before swap resize"

sudo swapoff -a || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
sudo rm -f /mnt/swapfile /swapfile

zram_module() {
	sudo modprobe zram && return 0
	sudo apt-get update -qq &&
		sudo apt-get install -y "linux-modules-extra-$(uname -r)" &&
		sudo modprobe zram
}

if zram_module; then
	zram_dev="$(sudo zramctl --find --size "${SWAP_GB}G" --algorithm zstd)" || zram_dev=""
	if [ -n "$zram_dev" ] && sudo mkswap "$zram_dev" && sudo swapon --priority 100 "$zram_dev"; then
		"$DUMP" "after swap resize → ${SWAP_GB}G zram at ${zram_dev}"
		exit 0
	fi
	echo "zram swap could not be set up; falling back to a swapfile" >&2
	if [ -n "$zram_dev" ]; then
		sudo zramctl --reset "$zram_dev" || echo "zramctl --reset ${zram_dev} failed" >&2
	fi
else
	echo "no zram module on this runner kernel; falling back to a swapfile" >&2
fi

if mountpoint -q /mnt 2>/dev/null; then
	mnt_free=$(df --output=avail -B1G /mnt | tail -n1 | tr -d ' ')
else
	mnt_free=0
fi
root_free=$(df --output=avail -B1G / | tail -n1 | tr -d ' ')

echo "Target swap: ${SWAP_GB}G. Free: / ${root_free}G, /mnt ${mnt_free}G (separate mount: $(mountpoint -q /mnt 2>/dev/null && echo yes || echo no))"

storage_on_mnt=no
if mountpoint -q /mnt 2>/dev/null && containerd_dev="$(stat -c %d /var/lib/containerd 2>/dev/null)" &&
	[ "$containerd_dev" = "$(stat -c %d /mnt)" ]; then
	storage_on_mnt=yes
fi

if [ "$storage_on_mnt" = yes ] && [ "$root_free" -ge "$MIN_FREE_GB" ]; then
	target=/swapfile
	chosen="/ (containerd and Docker live on /mnt)"
elif [ "$mnt_free" -ge "$MIN_FREE_GB" ]; then
	target=/mnt/swapfile
	chosen="/mnt (separate partition)"
elif [ "$root_free" -ge "$MIN_FREE_GB" ]; then
	target=/swapfile
	chosen="/ (no separate /mnt)"
else
	echo "Neither / nor /mnt has ${MIN_FREE_GB} GB free for a ${SWAP_GB} GB swapfile" >&2
	df -h / /mnt >&2
	exit 1
fi

echo "Chose ${chosen}: creating ${SWAP_GB}G swapfile at ${target}"

sudo fallocate -l "${SWAP_GB}G" "$target"
sudo chmod 600 "$target"
sudo mkswap "$target"
sudo swapon "$target"

"$DUMP" "after swap resize → ${SWAP_GB}G at ${target}"
