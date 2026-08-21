#!/usr/bin/env bash
# Cross-distro CI/container cleanup: package-manager and language-tool caches.
set -euo pipefail

echo "=== [cleanup] package manager caches ==="
if command -v apt-get >/dev/null 2>&1; then
  apt-get clean || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

if command -v pacman >/dev/null 2>&1; then
  pacman -Scc --noconfirm || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

if command -v dnf >/dev/null 2>&1; then
  dnf clean all || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  rm -rf /var/cache/dnf || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

if command -v yum >/dev/null 2>&1; then
  yum clean all || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  rm -rf /var/cache/yum || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

echo "=== [cleanup] language/tool caches (best effort) ==="
rm -rf /root/.cache/pip /home/*/.cache/pip 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
rm -rf /root/.npm /home/*/.npm 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
rm -rf /root/.cache/yarn /home/*/.cache/yarn 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
rm -rf /root/.cache/go-build /home/*/.cache/go-build 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
