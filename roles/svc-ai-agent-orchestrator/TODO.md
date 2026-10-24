# TODO

- `CRON_ENTRIES` and `CHANNELS` are passed to the container as JSON the deploy renders, so the running revision reads a frozen copy of the schedules and the enabled channels. Aggregating `cron.yml` from every deployed agent role into `services.agent-orchestrator.cron_entries` at inventory time is the remaining wiring; until then an inventory sets the list explicitly. Verify on a cluster that a schedule edit reaches the orchestrator on the next deploy rather than needing a restart.
