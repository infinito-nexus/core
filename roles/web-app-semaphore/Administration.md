# Administration

## Single point of failure

Semaphore is a single point of failure for every workspace.
Its database holds each workspace project with its templates, inventories, repositories, environments and runner rows, and its key store holds the private half of every workspace's repository read key.
While Semaphore is down, no workspace task, no `workspace apply`, no `members` task and no provisioning runs, for any workspace.

## Restore

A restore takes one generation of [svc-bkp-volume-2-local](../svc-bkp-volume-2-local/README.md#backup-set) plus the inventory.
Semaphore's database dump is in the generation; its access key encryption key, the credential `access_key_encryption` of `meta/secrets.yml`, is only in the inventory.
Without that key every key stored in the database stays unreadable, so no workspace task clones its repository.

After the restore, `workspace apply` runs once for every workspace project and rebuilds the runner compose projects, token files and egress lists from the database and OpenBao.

The deploy drill of `svc-bkp-volume-2-local` measures the restore time of this sequence in its workspace pass and logs it as `workspace drill: restore took <seconds>s`; the outage of every workspace lasts at least that long.
