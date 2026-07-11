# DR drill: backup + restore

Marker files seeded into the live NFS volume and into the manager's host
secrets travel the full backup chain forward and are recovered back onto
the live instance; the drill passes only when every marker survives the
whole loop.

```mermaid
flowchart TB
    subgraph forward["💾 Backup (solid: the deployed systemd units end to end)"]
        direction TB
        vol["📂 Live NFS volume + docker volume<br/>marker seeded"]:::live
        sec["🔑 Host secrets on the manager<br/>(secrets, CA, ACME, node identity) marker seeded"]:::live
        localbkp["🗄️ Local backups on manager + NFS server<br/>volume / nfs / secrets generation snapshots"]:::store
        pulled["🗄️ Backup host<br/>pulled generations (remote-2-local unit, rsync over ssh, pull-only)"]:::store
        usb["🔒 Encrypted USB (LUKS)<br/>hard-linked snapshot (local-2-device unit)"]:::device
        vol -->|backup units| localbkp
        sec -->|secrets unit| localbkp
        localbkp -->|remote pull| pulled -->|device sync| usb
    end

    subgraph recovery["♻️ Recovery (stack stopped, volume wiped first)"]
        direction TB
        restored["📁 Restore root on the backup host<br/>newest snapshot after luksOpen"]:::store
        export["📂 Live NFS export<br/>rebuilt from the restored generation"]:::live
        volume["📦 Docker volume<br/>rebuilt on the manager"]:::live
        secrets["🔑 Host secrets<br/>rebuilt on the manager (marker cleared first)"]:::live
        verified["✅ Stack redeployed<br/>markers verified on the live instance"]:::ok
        usb -.->|decrypt + recover| restored
        restored -.->|restore export| export
        restored -.->|restore volume| volume
        restored -.->|restore secrets| secrets
        export -.-> verified
        volume -.-> verified
        secrets -.-> verified
    end

    classDef live fill:#f1f8f6,stroke:#d5e7e2,color:#455a64;
    classDef store fill:#f3f7fb,stroke:#d6e2ee,color:#455a64;
    classDef device fill:#fbf3f6,stroke:#eed9e2,color:#455a64;
    classDef ok fill:#f3f9f4,stroke:#d9ecdc,color:#455a64;
    style forward fill:#ffffff,stroke:#e6e6e6;
    style recovery fill:#ffffff,stroke:#e6e6e6;
```
