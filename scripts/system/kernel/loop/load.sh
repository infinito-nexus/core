#!/usr/bin/env bash
# shellcheck shell=bash
#
# Load the kernel's loop driver so the swarm backup DR drill can attach its
# simulated LUKS 'USB'. The drill runs inside a node container that has no
# udev and cannot load modules itself: it materialises /dev/loopN with mknod,
# but those nodes are dead until the driver is present on the host. Without
# it cryptsetup aborts with "loop device with autoclear flag is required"
# roughly three hours into a swarm round.
#
# Use `make kernel-loop-load` rather than calling this script directly.

set -euo pipefail

modprobe loop

if [ ! -c /dev/loop-control ]; then
	echo "FAILURE: /dev/loop-control absent after 'modprobe loop'" >&2
	exit 1
fi

echo "loop driver ready: $(losetup -a | wc -l) device(s) currently attached"
