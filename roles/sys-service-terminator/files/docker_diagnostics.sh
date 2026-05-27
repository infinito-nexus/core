#!/usr/bin/env bash
#
# Best-effort Docker diagnostics for sys-service-terminator.
# Never fails hard (always exits 0).

set -u

TAIL="${SYS_SERVICE_RUNNER_DOCKER_LOG_TAIL:-200}"
INCLUDE_EXITED="${SYS_SERVICE_RUNNER_DOCKER_INCLUDE_EXITED:-true}"

echo "============================================================"
echo "=== DOCKER DIAGNOSTICS (best-effort)"
echo "============================================================"
echo "tail=${TAIL} include_exited=${INCLUDE_EXITED}"
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "[docker-diag] docker CLI not found - skipping."
  exit 0
fi

echo "--- container version ---"
container version 2>&1 || true
echo

echo "--- container info (short) ---"
container info 2>/dev/null | sed -n '1,120p' || true
echo

echo "--- container ps ---"
if [ "${INCLUDE_EXITED}" = "true" ]; then
  container ps -a --no-trunc 2>&1 || true
else
  container ps --no-trunc 2>&1 || true
fi
echo

if [ "${INCLUDE_EXITED}" = "true" ]; then
  ids="$(container ps -aq 2>/dev/null || true)"
else
  ids="$(container ps -q 2>/dev/null || true)"
fi

if [ -z "${ids}" ]; then
  echo "[docker-diag] No containers found."
  exit 0
fi

echo "[docker-diag] Found $(echo "${ids}" | wc -w | tr -d ' ') containers. Dumping logs..."
echo

for id in ${ids}; do
  name="$(container inspect -f '{{.Name}}' "${id}" 2>/dev/null | sed 's#^/##' || true)"
  status="$(container inspect -f '{{.State.Status}}' "${id}" 2>/dev/null || true)"
  health="$(container inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${id}" 2>/dev/null || true)"
  image="$(container inspect -f '{{.Config.Image}}' "${id}" 2>/dev/null || true)"

  echo "------------------------------------------------------------"
  echo ">>> ${name:-<unknown>} (id=${id})"
  echo "    status=${status:-?} health=${health:-n/a}"
  echo "    image=${image:-?}"
  echo "------------------------------------------------------------"
  container logs --tail "${TAIL}" "${id}" 2>&1 || true
  echo
done

exit 0
