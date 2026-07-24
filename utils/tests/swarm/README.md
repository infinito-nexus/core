# Swarm test inventory extension

`extend_inventory.py` expands a provisioned swarm-test inventory so the static
validator and the deploy see every group the run will use. It reads `APP_ID`,
`INV_PATH` and `SWARM_NAME` from the environment, merges the computed groups
into `INV_PATH`, and writes a sibling `backup.yml` for the second (backup-host)
play.

## Flow

```mermaid
flowchart TD
    ENV["env: SWARM_NAME, APP_ID, INV_PATH"] --> MAIN["main()"]

    MAIN --> TOPO["_host_topology(app_id)"]
    MAIN --> DEP["_placement_dep_groups(app_id)"]
    MAIN --> BKP{"volume / secrets backup\nrole in derive_includes(app_id)?"}
    MAIN --> NBKP{"svc-bkp-nfs-2-local in\nderive_includes(svc-storage-nfs-server)?"}

    TOPO --> T1["app_id → manager (+ workers unless manager-placed)"]
    TOPO --> T2["svc-swarm-node → manager + workers"]
    TOPO --> T3["svc-swarm-manager → manager"]
    TOPO --> T4["svc-storage-nfs-client → manager + workers"]
    TOPO --> T5["svc-storage-nfs-server → nfs-server"]

    DEP --> D1["derive_includes(app_id)\nrole with placement=manager → manager"]

    BKP -- yes --> B1["svc-bkp-volume-2-local,\nsvc-bkp-secrets-2-local → manager"]
    BKP -- no --> SKIP["skip app-induced backup legs"]
    NBKP -- yes --> NFS["svc-bkp-nfs-2-local → nfs-server"]
    NBKP -- no --> NSKIP["skip nfs-backup leg"]

    T1 & T2 & T3 & T4 & T5 & D1 & B1 & NFS --> MERGE["merge groups into all.children"]

    MERGE --> OUT1["write INV_PATH (devices.yml)"]
    MAIN --> OUT2["write backup.yml:\nsvc-bkp-remote-2-local,\nsvc-bkp-local-2-device → backup host"]
```

## Groups

| Group | Host | Condition |
| --- | --- | --- |
| `APP_ID` | manager, workers | workers dropped when the role is `placement: manager` |
| `svc-swarm-node` | manager, workers | always |
| `svc-swarm-manager` | manager | always |
| `svc-storage-nfs-client` | manager, workers | always |
| `svc-storage-nfs-server` | nfs-server | always |
| dep roles from `derive_includes` | manager | role declares `placement: manager` |
| `svc-bkp-volume-2-local` | manager | `derive_includes(APP_ID)` pulls it in via the `container_backup` consumer |
| `svc-bkp-secrets-2-local` | manager | `derive_includes(APP_ID)` pulls it in |
| `svc-bkp-nfs-2-local` | nfs-server | `derive_includes(svc-storage-nfs-server)` pulls it in via the `nfs_backup` consumer |
| `svc-bkp-remote-2-local`, `svc-bkp-local-2-device` | backup host | always, written to `backup.yml` |

Node names come from `default.env` (`INFINITO_SWARM_*_NAME`) with the
`SWARM_NAME` prefix. `INFINITO_APP_VARIANTS` feeds `derive_includes` to select
the active variant.
