#!/usr/bin/env bash
# Wait for the seeder's migrations, then exec the app entrypoint.
#
# Swarm ignores depends_on, so web and worker would start while the seeder is
# still migrating and die on ActiveRecord::PendingMigrationError.
#
# The wait is bounded on purpose. The probe fails both for pending migrations
# and for an unreachable database, so an unbounded loop would spin forever
# whenever the database is down. Past the deadline the entrypoint starts regardless,
# which is exactly today's behaviour: the worst case stays the crash loop that
# already exists, never a service that refuses to come up.
#
# Argv:
#   $1 deadline_seconds -- how long to wait before starting anyway
#   $2 poll_seconds     -- sleep between probes
#   $3.. entrypoint     -- the upstream start command to exec
set -euo pipefail

deadline_seconds="${1:?deadline_seconds required}"
poll_seconds="${2:?poll_seconds required}"
shift 2
[ "$#" -gt 0 ] || {
	echo "await_migrations: entrypoint required" >&2
	exit 2
}

schema_is_current() {
	local status
	status=$(bundle exec rails db:migrate:status 2>/dev/null) || return 1
	! grep -q -E '^[[:space:]]*down[[:space:]]' <<<"$status"
}

deadline=$(($(date +%s) + deadline_seconds))
while [ "$(date +%s)" -lt "$deadline" ]; do
	if schema_is_current; then
		echo "await_migrations: schema is current, starting $1"
		exec "$@"
	fi
	sleep "$poll_seconds"
done

echo "await_migrations: deadline of ${deadline_seconds}s reached, starting $1 regardless" >&2
exec "$@"
