#!/usr/bin/env bash
#
# Diagnostic dump for a single container, used by
# roles/svc-db-postgres/tasks/02_init.yml when the readiness wait
# fails. The container name is passed in $1 so this script stays
# Jinja-free.
set -e

CONTAINER="${1:?usage: $0 <container_name>}"

echo "== Container state =="
container inspect --format 'Name={{.Name}} State={{.State.Status}} ExitCode={{.State.ExitCode}} StartedAt={{.State.StartedAt}} Restarting={{.State.Restarting}}' "$CONTAINER"

echo
echo "== Image =="
container inspect --format 'Image={{.Config.Image}}' "$CONTAINER"

echo
echo "== Mounts =="
container inspect --format '{{range .Mounts}}{{.Type}}:{{.Source}}->{{.Destination}}{{"\n"}}{{end}}' "$CONTAINER"

echo
echo "== Env (redacted) =="
container inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | sed -E 's/=.*/=***REDACTED***/'
