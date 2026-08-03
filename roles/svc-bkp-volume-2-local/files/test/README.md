# Deploy drills for `svc-bkp-volume-2-local`

These scripts run **on the deployed host**, not on the controller. `test-e2e-cli`
renders `templates/test.env.j2` into the environment and calls `test.sh`, which
orchestrates the rest. They use `systemctl`, the `container` wrapper and
`/etc/machine-id`, so they only make sense where the role actually deployed.

## Orchestration

`test.sh` runs two different passes, selected by `ASYNC_ENABLED`. The snapshot
probe runs first in both, because it depends on nothing the backup produces.

```mermaid
flowchart TD
    ENV["test-e2e-cli renders test.env.j2<br>and calls test.sh"] --> HOST{"BKP_TEST_IS_STACK_HOST"}
    HOST -->|false| SKIP["exit 0<br>the role deploys on the stack host only"]
    HOST -->|true| PROBE["snapshot_probe.sh<br>runs on every deploy"]
    PROBE --> WAIT["wait for the backup unit to terminate,<br>then force one post-deploy run"]
    WAIT --> COUNT{"generations stored"}
    COUNT -->|none| FAIL["fail: nothing was backed up"]
    COUNT -->|"some, no backup subjects on the host"| EMPTY["exit 0<br>a stamped empty generation is the expected outcome"]
    COUNT -->|some| PASS{"ASYNC_ENABLED"}
    PASS -->|true| ASYNC["verify_backup.sh<br>requires two differential generations"]
    PASS -->|false| SYNC["verify_backup.sh<br>restore_cycle.sh<br>db_restore.sh"]
```

## `snapshot_probe.sh`

Drives `baudolo-snapshot`, the launcher that decides per run whether baudolo may
capture the volumes from a filesystem snapshot instead of copying the live tree.
That decision reads mountinfo, inode numbers and `btrfs subvolume list`, so it
cannot be answered by a unit test — it needs a filesystem that really exists.

The probe therefore builds a **throwaway** btrfs on a loop device and puts a stub
on `PATH` in place of the docker daemon. The host's real data root is never
touched, and no state survives the run.

```mermaid
flowchart TD
    START["snapshot_probe.sh"] --> DEPLOYED{"launcher executable?"}
    DEPLOYED -->|no| BAD["fail: the unit's ExecStart is missing"]
    DEPLOYED -->|yes| NEVER["--mode never must hand argv through byte-identically"]
    NEVER --> TOOLS{"root, mkfs.btrfs, losetup,<br>a free loop device?"}
    TOOLS -->|no| SKIPPED["skip the matrix<br>on such a host the launcher declines anyway"]
    TOOLS -->|yes| BUILD["truncate + mkfs.btrfs + losetup + mount<br>subvolume as the fake data root<br>docker stub on PATH"]
    BUILD --> M1["plain local volume<br>expect --snapshot btrfs --snapshot-subject &lt;root&gt;"]
    M1 --> M2["volume declaring Options type=nfs<br>expect no flags"]
    M2 --> M3["subvolume outside the volume tree: expect flags<br>subvolume inside it: expect no flags"]
    M3 --> M4[".baudolo-* leftover of a killed run<br>expect flags, and the leftover gone"]
    M4 --> M5["plain directory as the root<br>auto: no flags, stated btrfs: exit 2"]
    M5 --> CLEAN["trap: umount, losetup -d, rm -rf"]
```

Each case pins one half of the contract: a snapshot is taken **only** where it
would be faithful, and where it would not be, `auto` degrades silently to the
live copy while a stated kind fails the run loudly.

### Running it from the host

It is a standalone script — no environment, no backup generation, no other drill.
It resolves `baudolo-snapshot` from `PATH`, so it tests whatever the role
deployed:

```bash
sudo bash roles/svc-bkp-volume-2-local/files/test/snapshot_probe.sh
```

Without `sudo` the first two assertions still run and the matrix reports `SKIP`,
which is the honest outcome: an unprivileged process cannot create a loop device,
and the launcher refuses to snapshot as non-root anyway.

To exercise it on a host without btrfs tooling, install `baudolo-snapshot` into
a throwaway privileged container and run it there. Note that a container's
`/dev` carries no `/dev/loopN` nodes, so `losetup --find` finds nothing and the
matrix reports `SKIP` unless they are created first (`mknod /dev/loop0 b 7 0`,
…) or the host's `/dev` is bind-mounted in.

## `verify_backup.sh`

Requires the newest generation to hold real payload — a volume counts when it has
a `files/` tree or a non-empty `sql` dump. In the async pass it additionally
requires `PREVIOUS_GENERATION` to be a distinct, older generation, which is what
proves the differential `--link-dest` chain advanced.

```mermaid
flowchart TD
    GEN["&lt;REPO_DIR&gt;/&lt;NEWEST_GENERATION&gt;"] --> VOLS{"volume dirs with files/ or sql/"}
    VOLS -->|none| F1["fail: the generation is empty"]
    VOLS -->|some| PAY{"payload non-empty?"}
    PAY -->|no| F2["fail: the generation holds only empty dirs"]
    PAY -->|yes| PREV{"PREVIOUS_GENERATION set?"}
    PREV -->|no| OK1["sync pass satisfied"]
    PREV -->|yes| DIFF{"distinct and older?"}
    DIFF -->|no| F3["fail: no differential advance"]
    DIFF -->|yes| OK2["async pass satisfied"]
```

## `restore_cycle.sh`

The destructive drill, sync pass only. It proves the backup is restorable rather
than merely present — the property a backup exists for.

```mermaid
flowchart TD
    SWARM{"swarm node?"} -->|yes| SK["skip: the down/up cycle races the reconciler"]
    SWARM -->|no| DOWN["compose down every running project"]
    DOWN --> WIPE["wipe each backed-up volume"]
    WIPE --> RESTORE["baudolo-restore from the newest generation"]
    RESTORE --> UP["compose up the projects again"]
    UP --> HEALTH{"every previously running container<br>healthy, or running when it has no healthcheck?"}
    HEALTH -->|no| FAIL["fail: the restore did not bring the host back"]
    HEALTH -->|yes| DONE["restore cycle passed"]
```

## `db_restore.sh`

Replays the text dumps into the databases the previous step restarted, using the
credentials from `databases.csv`.

```mermaid
flowchart TD
    CSV["databases.csv<br>instance;database;username;password"] --> ROWS{"row kind"}
    ROWS -->|"database = '*' (cluster dump)"| SKIPPED["skipped visibly<br>baudolo-restore has no cluster replay path"]
    ROWS -->|concrete database| REPLAY["baudolo-restore postgres/mariadb --empty<br>against the running container"]
    REPLAY --> RESULT{"replay exit"}
    RESULT -->|non-zero| FAIL["fail: the dump is not replayable"]
    RESULT -->|zero| DONE["dump replay passed"]
```
