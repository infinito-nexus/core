#!/usr/bin/env bash
#
# Dump host disk diagnostics before the Playwright runner starts so OOM
# / no-space failures (e.g. on GitHub-hosted runners) leave a usable
# audit trail. Invoked from
# roles/test-e2e-playwright/tasks/02_run_one.yml when MODE_DEBUG is true.
set -o pipefail

echo "== findmnt -T /mnt/docker =="
findmnt -T /mnt/docker || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "== df -h / /mnt /mnt/docker /var/lib/docker =="
df -h / /mnt /mnt/docker /var/lib/docker || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo '== container info | grep "Docker Root Dir" =='
container info | grep "Docker Root Dir" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "== du -xhd1 /usr /usr/local /usr/share /opt /mnt /var | sort -h =="
du -xhd1 /usr /usr/local /usr/share /opt /mnt /var 2>/dev/null | sort -h || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
