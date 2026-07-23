# DR drill: backup + restore

Marker files seeded into the live NFS volume and into the manager's host
secrets travel the full backup chain forward and are recovered back onto
the live instance; the drill passes only when every marker survives the
whole loop. `base.sh` runs the nine steps below; the numbers in both
diagrams are its `[n/9]` log markers.

## Step sequence (who does what)

```mermaid
sequenceDiagram
    autonumber
    participant N as nfs-server
    participant M as manager
    participant B as backup host
    participant U as LUKS "USB" (loop img on B)

    Note over N,M: [1/9] seed markers
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

    Note over M: [6/9] full disaster teardown
    alt stack workload
        M->>M: docker stack rm + wait
    else node-local workload
        M->>M: stop compose project on every node
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

    Note over M,N: matrix update pass redeploys, then verify_recovered_marker.sh asserts the live marker
```

## Data flow (what is proven)

```mermaid
flowchart TB
    subgraph forward["💾 Backup (solid: the deployed systemd units end to end)"]
        direction TB
        vol["📂 [1] Live NFS volume + docker volume<br/>marker seeded"]:::live
        sec["🔑 [1] Host secrets on the manager<br/>(secrets, CA, ACME, node identity) marker seeded"]:::live
        localbkp["🗄️ [2-3] Local backups on manager + NFS server<br/>volume / nfs / secrets generation snapshots"]:::store
        pulled["🗄️ [4] Backup host<br/>pulled generations (remote-2-local unit, rsync over ssh, pull-only)"]:::store
        usb["🔒 [5] Encrypted USB (LUKS)<br/>hard-linked snapshot (local-2-device unit)"]:::device
        vol -->|backup units| localbkp
        sec -->|secrets unit| localbkp
        localbkp -->|remote pull| pulled -->|device sync| usb
    end

    teardown["🛑 [6] Full disaster:<br/>stack rm (stack workload) or<br/>compose stop on every node (node-local workload),<br/>then export wiped"]:::dead

    subgraph recovery["♻️ Recovery (dashed: the recover CLI, newest generation only)"]
        direction TB
        restored["📁 [7] Restore root on the backup host<br/>newest snapshot after luksOpen (pulled tree + loop img freed)"]:::store
        export["📂 [8] Live NFS export<br/>volume subtree rebuilt, ganesha + client mounts refreshed"]:::live
        volume["📦 [9] Docker volume<br/>rebuilt on the manager"]:::live
        secrets["🔑 [9] Host secrets<br/>rebuilt on the manager (marker cleared first)"]:::live
        verified["✅ Update pass redeploys<br/>markers verified on the live instance"]:::ok
        usb -.->|decrypt + recover| restored
        restored -.->|restore export| export
        restored -.->|restore volume| volume
        restored -.->|restore secrets| secrets
        export -.-> verified
        volume -.-> verified
        secrets -.-> verified
    end

    forward --> teardown --> recovery

    classDef live fill:#f1f8f6,stroke:#d5e7e2,color:#455a64;
    classDef store fill:#f3f7fb,stroke:#d6e2ee,color:#455a64;
    classDef device fill:#fbf3f6,stroke:#eed9e2,color:#455a64;
    classDef dead fill:#fdf2f2,stroke:#eddada,color:#455a64;
    classDef ok fill:#f3f9f4,stroke:#d9ecdc,color:#455a64;
    style forward fill:#ffffff,stroke:#e6e6e6;
    style recovery fill:#ffffff,stroke:#e6e6e6;
```

## Applicability

- The drill runs whenever the app declares an NFS-flagged volume
  (`PRIMARY_NFS_VOLUME`); apps without one skip it, since there is nothing
  to prove a restore against.
- The workload form only changes step 6: stack workloads get
  `docker stack rm`, `workload: node-local` roles get their compose
  project stopped on every node. Every other step operates on volumes,
  the NFS export and the deployed backup units, independent of the
  orchestrator.
- Runs once per app, in the variant-0 CI job, between the matrix's first
  deploy and its update pass.
