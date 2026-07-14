# Swarm deploy test harness

Simulates a full Docker Swarm cluster on a single CI runner (or host via
`make swarm-zombie` / `make roundtrip`) and deploys one application
through it end to end: provision an inventory, deploy every variant
round with the in-deploy Playwright e2e, run the backup+restore DR drill
between rounds, then prove state survives a worker reschedule.

The cluster consists of privileged systemd containers on a dedicated lab
bridge (`192.168.244.0/24`, MTU 1400): three swarm nodes (1 manager +
2 workers), a non-swarm NFSv4 server serving the shared volume storage,
and a non-swarm backup host for the DR drill. The node image
([`compose/swarm/Dockerfile`](../../../../compose/swarm/Dockerfile))
bakes python3 + dnsmasq; the containers and the lab network are declared
in [`compose/swarm/compose.yml`](../../../../compose/swarm/compose.yml) (project
`${SWARM_NAME}`, backup host behind the `drill` profile) and started by
one `docker compose up` in `routine/01_bootstrap.sh`. Lab DNS is provisioned
by `compose/swarm/playbook.yml` over `ansible_connection: docker` (Ansible never
uses ssh here); swarm init/join itself happens inside the deploy via the
`svc-swarm-node` role, not in any bring-up script.

## Flow

```mermaid
flowchart TB
    subgraph infra["🥾 Cluster bring-up (per matrix app)"]
        direction TB
        topo["🗺️ utils/topology/base + export<br/>SPOT node names + NFS paths → GITHUB_ENV"]:::infra
        cluster["🐝 01_bootstrap.sh<br/>host side: pre-clean, compose build + up<br/>all 5 nodes + lab network, sudo .deb build"]:::infra
        boot["🧱 compose/swarm/playbook.yml (over docker connection)<br/>systemd wait, NFS-export wipe, IPs → GITHUB_ENV,<br/>lab DNS, repo + .deb install on every node"]:::infra
        topo --> cluster --> boot
    end

    subgraph deploy["🚀 Matrix deploy (per variant round)"]
        direction TB
        prov["📋 02_provision_inventory<br/>per-round inventory + extend_inventory + write_extras"]:::deploy
        dep["📦 deploy round N: swarm init/join (svc-swarm-node)<br/>+ docker stack deploy + Playwright e2e"]:::deploy
        conv["✅ 03_wait_converge + 04_verify_reachable"]:::deploy
        purge["🧽 purge_stacks (between rounds)"]:::deploy

        subgraph drill["🔐 routine/backup/base.sh (DR drill, once, after round 1)"]
            direction TB
            s1["1️⃣ seed marker into the live NFS volume"]:::drill
            s2["2️⃣ trigger backup units<br/>volume-2-local @ manager, nfs-2-local @ NFS server"]:::drill
            s3["3️⃣ locate the generation holding the marker"]:::drill
            s4["4️⃣ pull to the backup host<br/>remote-2-local over the user-backup ssh wrapper"]:::drill
            s5["5️⃣ mirror to a LUKS loop 'USB'<br/>local-2-device script.py"]:::drill
            s6["6️⃣ recover device → local root<br/>local-2-device recover.py (luksOpen + newest snapshot)"]:::drill
            s7["7️⃣ stack rm + wipe volume, recover root → export<br/>nfs-2-local recover.py"]:::drill
            s8["8️⃣ recover volume + secrets backups<br/>volume-2-local + secrets recover.py<br/>(marker verified after the update pass)"]:::drill
            s1 --> s2 --> s3 --> s4 --> s5 --> s6 --> s7 --> s8
        end

        prov --> dep --> conv --> drill --> purge
    end

    subgraph chaos["💪 Reschedule chaos (after the matrix)"]
        direction TB
        seed["🌱 05_seed_content<br/>marker on the NFS volume"]:::chaos
        drain["🩸 06_drain_worker<br/>drain the app's worker, force reschedule"]:::chaos
        assert["🔎 07_assert_state<br/>marker survived + app reachable on new node"]:::chaos
        seed --> drain --> assert
    end

    subgraph teardown["🧹 Always"]
        direction TB
        diag["📊 collect: diagnostics / playwright reports +<br/>workflow-level recursive container.py rescue snapshot"]:::teardown
        clean["🗑️ utils/clean/teardown (kill nodes + lab network)"]:::teardown
        diag --> clean
    end

    subgraph lab["🌐 Lab bridge 192.168.244.0/24 (MTU 1400)"]
        direction LR
        nMgr["👑 swarm-mgr-01 (manager)<br/>stacks, volume-2-local, user-backup, sshd"]:::mgr
        nW1["⚙️ swarm-wrk-01 (worker)"]:::wrk
        nW2["⚙️ swarm-wrk-02 (worker)"]:::wrk
        nNfs["📦 nfs-server (non-swarm)<br/>NFS export, nfs-2-local, sshd"]:::nfsnode
        nBkp["💽 backup-host (non-swarm)<br/>deployed remote-2-local + local-2-device units,<br/>LUKS device"]:::bkpnode
    end

    infra --> deploy --> chaos --> teardown

    cluster -->|▶️ compose up all 5| nMgr & nW1 & nW2 & nNfs & nBkp
    boot -->|🌐 hosts + dnsmasq| nMgr & nW1 & nW2 & nNfs
    boot -->|📥 repo + .deb install| nMgr & nW1 & nW2 & nNfs & nBkp
    dep -->|🚀 swarm init/join + docker stack deploy| nMgr
    s2 -->|⏱️ trigger volume + nfs units| nMgr & nNfs
    s4 -->|⬇️ pull backup@source| nBkp
    s7 -->|♻️ wipe + recover export| nNfs
    s8 -->|🚀 redeploy| nMgr
    seed -->|🌱 marker on export| nNfs
    drain -->|🩸 drain a worker| nMgr
    clean -->|🗑️ kill + remove| nMgr & nW1 & nW2 & nNfs & nBkp

    nMgr -. 📨 schedules app tasks .-> nW1 & nW2
    nMgr -. 💾 NFS-backed volumes .-> nNfs
    nW1 -. 🔗 NFS mount .-> nNfs
    nW2 -. 🔗 NFS mount .-> nNfs
    nBkp -. 🔑 pull over ssh .-> nMgr & nNfs

    classDef infra fill:#f3f7fb,stroke:#d6e2ee,color:#455a64;
    classDef deploy fill:#f3f9f4,stroke:#d9ecdc,color:#455a64;
    classDef drill fill:#fbf6f0,stroke:#eee1cf,color:#455a64;
    classDef chaos fill:#fbf4f4,stroke:#eed9d9,color:#455a64;
    classDef teardown fill:#f7f8f9,stroke:#e3e6e9,color:#455a64;
    classDef mgr fill:#f6f3fb,stroke:#e0d7ee,color:#455a64;
    classDef wrk fill:#f8f4fa,stroke:#e6dcec,color:#455a64;
    classDef nfsnode fill:#f1f8f6,stroke:#d5e7e2,color:#455a64;
    classDef bkpnode fill:#fbf3f6,stroke:#eed9e2,color:#455a64;
    style infra fill:#ffffff,stroke:#e6e6e6;
    style deploy fill:#ffffff,stroke:#e6e6e6;
    style drill fill:#ffffff,stroke:#e6e6e6;
    style chaos fill:#ffffff,stroke:#e6e6e6;
    style teardown fill:#ffffff,stroke:#e6e6e6;
    style lab fill:#ffffff,stroke:#e6e6e6;
```

The drill proves the full `svc-bkp-*` chain forward through the DEPLOYED
systemd units on every host (volume + secrets on the manager, nfs on the
export host, remote pull + device sync on the backup host) and every
`recover.py` back (device -> local root -> NFS export, docker volume and
host secrets into the live system paths), with marker files that must
survive the whole loop: the matrix update pass boots the recovered stack
and `verify_recovered_marker.sh` asserts the marker on the live volume. It
reuses the round-1 stack instead of spinning a dedicated cluster, and skips
cleanly when the app declares no NFS-flagged volume. The backup host is started by `routine/01_bootstrap.sh` (drill
profile) and receives its two roles via `extend_inventory`; the pull
trust (backup keypair) and the role config (backup_providers, device
mount/target/source) come from `utils/tests/swarm/write/extras.py`.

## Scripts

The sequenced flow lives in `routine/`, the naming SPOT in `utils/topology/`,
shared helpers in `utils/`, and
the cluster declaration (image, containers, network, DNS play) in
`compose/swarm/` + `compose/swarm/compose.yml`.

| Stage | Script | Purpose |
|---|---|---|
| bring-up | `utils/topology/base.sh` | SPOT: node names + NFS export/state paths (sourced, not run) |
| bring-up | `utils/topology/export.sh` | write the topology SPOT into `$GITHUB_ENV` |
| bring-up | `compose/swarm/compose.yml` + `compose/swarm/Dockerfile` | declare the 5 node containers, node image + lab network (compose SPOT) |
| bring-up | `routine/01_bootstrap.sh` | one CI step, host side: pre-clean, `compose build` + one `compose up`, sudo `.deb` build, then the play |
| bring-up | `compose/swarm/playbook.yml` | node side over docker connection: systemd wait, NFS-export wipe, IPs into `$GITHUB_ENV`, lab DNS, repo + `.deb` install |
| deploy | `routine/02_provision_inventory.sh` | provision the per-round inventory |
| deploy | `routine/03_wait_converge.sh` | wait for every stack service to converge |
| deploy | `routine/04_verify_reachable.sh` | probe the app is reachable in-cluster |
| deploy | `routine/backup/base.sh` (+ per-host routines in `routine/backup/`) | backup+restore DR drill between rounds |
| deploy | `utils/clean/purge_stacks.sh` | remove prior-round stacks between rounds |
| chaos | `routine/05_seed_content.sh` | seed a marker on the NFS volume |
| chaos | `routine/06_drain_worker.sh` | drain the app's worker + force reschedule |
| chaos | `routine/07_assert_state.sh` | assert the marker + reachability survived |
| teardown | `utils/collect/diagnostics.sh` | collect stack/service diagnostics on failure |
| teardown | `utils/collect/playwright_reports.sh` | pull Playwright reports from the manager |
| teardown | `utils/clean/teardown.sh` | kill the nodes + remove the lab network |
| helper | `utils/_context.sh` | per-app facts (entity, service, NFS volume, probes) |
| helper | `utils/unmount_nfs_mounts.sh` | best-effort NFS unmount before node removal |
| recovery | `utils/clean/all.sh` | reap leftover clusters across every cluster id |
| recovery | `utils/clean/stale_nfs.sh` | recover stale in-namespace NFS mounts |

The matrix orchestrator
(`utils/tests/swarm/matrix.py`) drives the deploy stage
per variant round; the workflow `.github/workflows/test-deploy-swarm.yml`
drives the surrounding stages. Run one app locally with
`make swarm-zombie app=<id>` (keeps the cluster for inspection) or the
whole matrix via `make roundtrip`.
