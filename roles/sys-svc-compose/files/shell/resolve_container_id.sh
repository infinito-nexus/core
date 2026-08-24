#!/bin/bash
# Resolve a Swarm service to the runtime container ID of its first
# running task. Callers pass STACK and SERVICE_KEY separately; the
# lookup composes `<stack>_<service>` because Docker Swarm names every
# service that way and accepts no prefix matching.
#
# Compose-mode callers never reach this script: the `container_address`
# lookup returns the bare service name unchanged when
# DEPLOYMENT_MODE == 'compose'.
#
# Uses the project-wide `container` wrapper for every container-engine
# call (per the no-raw-docker convention) so a podman substitution
# stays drop-in.
#
# Exit codes:
#   0   success -- prints the 12-char container ID to stdout
#   64  caller did not pass both args, or host is not a Swarm manager
#   65  service exists but has no running task
#   66  task exists but its container is not yet bound (transient)
set -eu

STACK="${1:-}"
SERVICE_KEY="${2:-}"
if [ -z "$STACK" ] || [ -z "$SERVICE_KEY" ]; then
  echo "resolve-container-id: STACK and SERVICE_KEY required" >&2
  exit 64
fi

SERVICE="${STACK}_${SERVICE_KEY}"

container node ls >/dev/null 2>&1 || {
  echo "resolve-container-id: must run on a Swarm manager node" >&2; exit 64; }

LOCAL_ID=$(container ps \
  --filter "label=com.docker.swarm.service.name=$SERVICE" \
  --filter status=running \
  --format '{{.ID}}' 2>/dev/null | head -1)
if [ -n "$LOCAL_ID" ]; then
  echo "${LOCAL_ID:0:12}"
  exit 0
fi

TASK_ID=$(container service ps \
  --filter desired-state=running \
  --no-trunc \
  --format '{{.ID}}' \
  "$SERVICE" 2>/dev/null | head -1)
[ -n "$TASK_ID" ] || {
  echo "resolve-container-id: no running task for service '$SERVICE'" >&2; exit 65; }

CONTAINER_ID=$(container inspect \
  --type=task \
  --format '{{.Status.ContainerStatus.ContainerID}}' \
  "$TASK_ID" 2>/dev/null)
[ -n "$CONTAINER_ID" ] || {
  echo "resolve-container-id: task $TASK_ID for '$SERVICE' has no container yet" >&2; exit 66; }

echo "${CONTAINER_ID:0:12}"
