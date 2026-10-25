# TODO

- `CRON_ENTRIES` and `CHANNELS` are passed to the container as JSON the deploy renders, so the running revision reads a frozen copy of the schedules and the enabled channels. The deploy folds every agent role's `cron.yml` onto the inventory `cron_entries` list via `lookup('agent_config', <role>, 'cron')`. Verify on a cluster that a schedule edit reaches the orchestrator on the next deploy rather than needing a restart.
