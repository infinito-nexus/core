#!/bin/sh
# @param $1 disc usage in percent above which every unused image and the build cache go
#
# Required environment:
#   SYS_SERVICE_CLEANUP_ANONYMOUS_VOLUMES  systemd unit name that removes the anonymous volumes

set -e

limit="$1"

echo "Cleaning up anonymous Docker volumes via systemd service..."
systemctl start "${SYS_SERVICE_CLEANUP_ANONYMOUS_VOLUMES}" || exit 1
if df --output=pcent | sed 1d | tr -d ' %' | awk -v limit="$limit" '$1 > limit { over = 1 } END { exit !over }'; then
  echo "A filesystem exceeds ${limit}%: pruning every unused image and the build cache..."
  container system prune -a -f || exit 2
else
  echo "No filesystem exceeds ${limit}%: pruning stopped containers, unused networks, dangling images and dangling build cache..."
  container system prune -f || exit 2
fi
echo "Docker prune cleanup finished."
