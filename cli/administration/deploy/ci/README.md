# CI Deploy Runs 🚦

Inspect and trigger the compose and swarm deploy-test runs for the branch you
are on. `status` summarises each role's per-mode result (docker, swarm, and an
aggregated all) from the last run; `trigger` dispatches a fresh manual run for
all roles, only the ones that failed last time, or an explicit list.
