# DR drill: backup + restore

Marker files seeded into the live NFS volume and into the manager's host
secrets travel the full backup chain forward and are recovered back onto
the live instance; the drill passes only when every marker survives the
whole loop. `base.sh` runs the nine steps below; the numbers in both
diagrams are its `[n/9]` log markers.

## Schema

The CI drill includes destructive database recovery. The disposable test
cluster keeps only the database engines and local registry available while
every database-writing workload, including shared dependencies such as
Discourse, is stopped. The normal matrix update remains the single source of
truth for bringing the workloads back.

```mermaid
flowchart LR
    seed["Seed pre-backup database probes"]
    backup["Run deployed backup units"]
    mutate["Write post-backup probes"]
    quiesce["Remove all database writers<br/>target stack + shared dependencies"]
    files["Recover NFS, volumes and secrets"]
    database["Restore SQL dumps into<br/>the real CI databases"]
    redeploy["Matrix update redeploys<br/>the desired state"]
    verify["Health + Playwright<br/>pre-backup probes present<br/>post-backup probes absent"]

    seed --> backup --> mutate --> quiesce --> files --> database --> redeploy --> verify
```

## Step sequence (who does what)

```mermaid
sequenceDiagram
    autonumber
    participant N as nfs-server
    participant M as manager
    participant D as database engines
    participant B as backup host
    participant U as LUKS "USB" (loop img on B)

    Note over M,D: role test seeds pre-backup DB probes, backs up, then seeds post-backup probes

    Note over N,M: [1/9] seed file markers
    N->>N: marker → live NFS volume dir
    M->>M: marker → host secrets dir

    Note over N,M: [2/9] trigger deployed backup units
    M->>M: svc-bkp-volume-2-local + secrets-2-local
    N->>N: svc-bkp-nfs-2-local

    Note over N,M: [3/9] locate the generation holding the marker
    N-->>M: find marker in files/*/<volume>/ (volume-scoped)

    Note over B: [4/9] pull via remote-2-local unit (rsync over ssh)
    B->>N: pull nfs generations
    B->>M: pull volume + secrets generations

    Note over B,U: [5/9] plug LUKS device, sync via local-2-device unit
    B->>U: hard-linked snapshot

    Note over M,D: [6/9] quiesce writers
    alt database handoff exists
        M->>M: remove all non-DB/non-registry stacks and containers
    else file-only drill
        M->>M: remove the target stack or node-local compose project
    end

    Note over B,U: [7/9] recover device → local root
    U-->>B: luksOpen + recover CLI → /var/tmp restore root
    B->>B: drop pulled tree + loop image (free disk)

    Note over N: [8/9] recover local root → live NFS export
    B-->>N: tar the volume subtree → recover CLI
    N->>N: [8b] restart ganesha, remount clients, coherence probe

    Note over M: [9/9] recover docker volume + host secrets
    B-->>M: volume generation → recover CLI
    B-->>M: secrets generation → recover CLI

    Note over M,D: [9b/9] restore selected SQL generation
    B-->>M: device-recovered volume backup repository
    M->>D: replay dumps while all writers remain stopped

    Note over M,N: matrix update redeploys; health, Playwright, file markers and DB before/after probes must pass
```

## Data flow (what is proven)

```mermaid
flowchart TB
    subgraph forward["💾 Backup (solid: the deployed systemd units end to end)"]
        direction TB
        vol["📂 [1] Live NFS volume + docker volume<br/>marker seeded"]:::live
        sec["🔑 [1] Host secrets on the manager<br/>(secrets, CA, ACME, node identity) marker seeded"]:::live
        dbpre["🗃️ Pre-backup DB probe<br/>included in the selected SQL generation"]:::live
        localbkp["🗄️ [2-3] Local backups on manager + NFS server<br/>volume / nfs / secrets generation snapshots"]:::store
        pulled["🗄️ [4] Backup host<br/>pulled generations (remote-2-local unit, rsync over ssh, pull-only)"]:::store
        usb["🔒 [5] Encrypted USB (LUKS)<br/>hard-linked snapshot (local-2-device unit)"]:::device
        vol -->|backup units| localbkp
        sec -->|secrets unit| localbkp
        dbpre -->|SQL dump| localbkp
        localbkp -->|remote pull| pulled -->|device sync| usb
    end

    dbpost["✍️ Post-backup DB probe<br/>must disappear after restore"]:::dead
    teardown["🛑 [6] Full disaster:<br/>all DB writers removed, including shared dependencies;<br/>only DB engines + registry remain,<br/>then export wiped"]:::dead

    subgraph recovery["♻️ Recovery (dashed: newest file snapshots + handed-off SQL generation)"]
        direction TB
        restored["📁 [7] Restore root on the backup host<br/>newest snapshot after luksOpen (pulled tree + loop img freed)"]:::store
        export["📂 [8] Live NFS export<br/>volume subtree rebuilt, ganesha + client mounts refreshed"]:::live
        volume["📦 [9] Docker volume<br/>rebuilt on the manager"]:::live
        secrets["🔑 [9] Host secrets<br/>rebuilt on the manager (marker cleared first)"]:::live
        database["🗃️ [9b] Live databases<br/>selected SQL generation replayed without writers"]:::live
        verified["✅ Update pass redeploys<br/>health + Playwright pass;<br/>file markers and DB before/after probes verified"]:::ok
        usb -.->|decrypt + recover| restored
        restored -.->|restore export| export
        restored -.->|restore volume| volume
        restored -.->|restore secrets| secrets
        restored -.->|restore SQL dumps| database
        export -.-> verified
        volume -.-> verified
        secrets -.-> verified
        database -.-> verified
    end

    forward --> dbpost --> teardown --> recovery

    classDef live fill:#f1f8f6,stroke:#d5e7e2,color:#455a64;
    classDef store fill:#f3f7fb,stroke:#d6e2ee,color:#455a64;
    classDef device fill:#fbf3f6,stroke:#eed9e2,color:#455a64;
    classDef dead fill:#fdf2f2,stroke:#eddada,color:#455a64;
    classDef ok fill:#f3f9f4,stroke:#d9ecdc,color:#455a64;
    style forward fill:#ffffff,stroke:#e6e6e6;
    style recovery fill:#ffffff,stroke:#e6e6e6;
```

## Applicability

- The first matrix round runs the complete file chain whenever the app
  declares an NFS-flagged volume (`PRIMARY_NFS_VOLUME`). A database handoff
  is destructive even without NFS: all writers are quiesced and the selected
  manager-local generation is restored.
- Later variant rounds skip the expensive file chain. If their role test
  hands off SQL dumps, they still run the destructive database restore and
  post-update probe verification; no Swarm restore is replaced by a guard.
- In a file-only drill, the workload form changes step 6: stack workloads
  get `docker stack rm`, while `workload: node-local` roles have their
  Compose project stopped on every node. A database handoff instead removes
  every non-database workload in either form.
- Runs between the sync and update pass. The full NFS/device chain runs once
  per app; database recovery runs in every round that produced a handoff.
