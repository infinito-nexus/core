#!/usr/bin/env bash
#
# Best-effort diagnostics for the PeerTube container after a plugin-install
# failure. Prints container state, health, resource limits, logs, stats,
# host memory, and OOM-killer evidence. Always exits 0 — the ansible rescue
# step is responsible for re-raising the failure after the dump.
#
# Usage: diagnostics.sh <container-name>
# Env:   PEERTUBE_OIDC_PLUGIN_INSTALL_MAX_OLD_SPACE_MB, PEERTUBE_MAX_OLD_SPACE_SIZE
#        (optional — printed into the report for correlation).

set -u

CONTAINER="${1:-peertube}"
INSTALL_HEAP_MB="${PEERTUBE_OIDC_PLUGIN_INSTALL_MAX_OLD_SPACE_MB:-?}"
MAIN_HEAP_MB="${PEERTUBE_MAX_OLD_SPACE_SIZE:-?}"

echo "============================================================"
echo "=== PEERTUBE DIAGNOSTICS (plugin-install failure)"
echo "============================================================"
echo "container=${CONTAINER}"
echo "install_heap_mb=${INSTALL_HEAP_MB} main_heap_mb=${MAIN_HEAP_MB}"
echo

echo "--- State ---"
container inspect --format \
  'Status={{.State.Status}} Running={{.State.Running}} Restarting={{.State.Restarting}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}} RestartCount={{.RestartCount}}' \
  "${CONTAINER}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- Health ---"
container inspect --format \
  '{{if .State.Health}}Status={{.State.Health.Status}} FailingStreak={{.State.Health.FailingStreak}}{{range .State.Health.Log}}{{println "log:" .ExitCode .Output}}{{end}}{{else}}no healthcheck configured{{end}}' \
  "${CONTAINER}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- Resource limits ---"
container inspect --format \
  'MemLimit={{.HostConfig.Memory}} MemSwap={{.HostConfig.MemorySwap}} NanoCpus={{.HostConfig.NanoCpus}} PidsLimit={{.HostConfig.PidsLimit}}' \
  "${CONTAINER}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- container stats (single snapshot) ---"
container stats --no-stream --no-trunc "${CONTAINER}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- container logs (last 250 lines) ---"
container logs --tail 250 "${CONTAINER}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- Host memory + swap ---"
free -h 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo
swapon --show 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
echo

echo "--- dmesg tail (OOM-killer evidence, best effort) ---"
dmesg -T 2>/dev/null | tail -n 80 | grep -Ei 'oom|kill|memory' \
  || echo 'no oom/kill evidence in dmesg tail'
echo

echo "============================================================"
echo "=== END PEERTUBE DIAGNOSTICS"
echo "============================================================"

exit 0
