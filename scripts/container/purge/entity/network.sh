#!/usr/bin/env bash
# Remove the per-entity default Docker network when it survives the
# entity-keyed compose-down primitive.
#
# `docker compose down --remove-orphans` only deletes networks that
# compose itself created (those carrying
# `com.docker.compose.network=default` + `com.docker.compose.project=<name>`
# labels). When the network exists with an empty / different label —
# typical after an inter-round matrix-deploy purge, or when a
# `community.docker.docker_network` Ansible call materialised the
# network before compose ran — compose deliberately leaves it
# untouched, and a subsequent `compose up` aborts with
#
#   network <entity> was found but has incorrect label
#   com.docker.compose.network set to "" (expected: "default")
#
# This primitive plugs that gap. It is invoked after the
# compose / dir / nginx primitives in `apps.sh`, so by the time it
# runs the entity's own containers should be gone. The script then:
#
#   1. Exits 0 if the network does not exist (idempotent).
#   2. Skips the removal when the network still has active container
#      endpoints — that proves a *shared* service (svc-db-mariadb,
#      svc-db-postgres, svc-db-openldap, svc-ai-ollama, …) is using
#      the network and the per-entity purge is NOT responsible for
#      tearing it down. The shared-service role's own purge handles
#      its own network when called.
#   3. Removes the orphan network when no endpoints are attached.
#
# The global `docker network prune -f` sweep that catches orphans
# whose names do NOT match the entity is the orchestrator's job
# (see `scripts/container/purge/apps.sh`) — running it once after
# the entity loop avoids paying the per-call listing cost N times.
#
# Failures of `docker network rm` (e.g. transient docker daemon
# hiccups) are logged but do NOT abort the overall purge — they
# would only surface again on the next `compose up`, where the
# error message is already actionable.
#
# Usage: ./network.sh <ENTITY>

set -euo pipefail

ENTITY="${1:?ENTITY is required (e.g. './network.sh matrix')}"

if docker network inspect "${ENTITY}" >/dev/null 2>&1; then
	endpoint_count="$(
		docker network inspect -f '{{ len .Containers }}' "${ENTITY}" 2>/dev/null || echo 0
	)"
	if [[ "${endpoint_count:-0}" -gt 0 ]]; then
		echo ">>> network '${ENTITY}' has ${endpoint_count} active endpoint(s); skipping"
	else
		label="$(
			docker network inspect -f '{{ index .Labels "com.docker.compose.network" }}' \
				"${ENTITY}" 2>/dev/null || echo ""
		)"
		if [[ "${label}" == "default" ]]; then
			# Compose-managed but compose-down apparently missed it — flag
			# it so the operator notices a pattern (stuck compose project).
			echo ">>> network '${ENTITY}' is compose-labeled but orphaned (no endpoints); removing"
		else
			echo ">>> orphan network '${ENTITY}' (compose label '${label}'); removing"
		fi
		if ! docker network rm "${ENTITY}" >/dev/null 2>&1; then
			echo "!!! WARNING: docker network rm '${ENTITY}' failed; leaving in place" >&2
		fi
	fi
fi
