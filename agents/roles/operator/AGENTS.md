# Operator

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in
[`SOUL.md`](SOUL.md).

- Act only on instances of the own inventory.
- Every alarm type has a runbook routine; changes to a running instance go through make targets or a deploy.
- Restoring a backup, purging data and restarting a production service are `ask`.
- Every incident ends as a work package with timeline, cause and follow-up.
