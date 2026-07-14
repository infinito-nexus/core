# Swarm test routine 🔁

Sequenced steps of the swarm lab run. Bring-up and the chaos phase are
workflow steps; the per-round loop in between is driven by
`utils.tests.swarm.matrix` (one round per variant of the
primary app). Highlighted boxes (⚡) are the moments a backup-executing
systemd unit actually starts. See [../README.md](../README.md) for
topology, naming SPOTs and helpers; the DR drill's own steps are
documented in [backup/README.md](backup/README.md).

```mermaid
flowchart TB
    boot["Bring up the simulated cluster:<br/>build + start the 5 node containers, wait for systemd,<br/>wire lab DNS + IPs, install the project on every node"]

    subgraph matrix["Variant matrix - one round per variant of the primary app"]
        purge["Remove the prior round's stacks<br/>(rounds after the first)"]
        prov["Provision the round's inventory and deploy the app stack"]
        t_pre["⚡ Service-loader preload (MODE_BACKUP):<br/>volume + secrets units instant-start on the manager,<br/>nfs unit on the export host - pre-state snapshot<br/>before the deploy mutates anything"]
        conv["Wait until every stack service converges"]
        reach["Probe the app is reachable in-cluster"]
        bkphost["Deploy the backup host<br/>(round 1 only: pull + device roles on bkp-01)"]
        t_term["⚡ Terminator at that play's end (MODE_BACKUP):<br/>remote-2-local pull force-starts on bkp-01<br/>(fails without the ssh trust the drill installs later)"]

        subgraph drill["Disaster-recovery drill (round 1 only)"]
            d1["Seed markers on the live NFS volume<br/>and in the manager secrets"]
            t_d2["⚡ Trigger the deployed backup units again:<br/>volume + secrets on the manager,<br/>nfs on the export host - markers get captured"]
            d3["Locate the backup generation<br/>holding the marker"]
            t_d4["⚡ Install the ssh pull identity, then start<br/>the remote-2-local unit: bkp-01 pulls every provider"]
            t_d5["⚡ Plug a LUKS loop device as simulated USB:<br/>the .mount unit fires the local-2-device unit"]
            d6["Recover device -> local backup root<br/>(full LUKS open)"]
            d7["Remove the stack, wipe the live NFS export,<br/>recover it from the local root"]
            d8["Recover the docker volume<br/>and the host secrets"]
            d9["Redeploy the stack, assert the marker<br/>is back on the live volume"]
            d1 --> t_d2 --> d3 --> t_d4 --> t_d5 --> d6 --> d7 --> d8 --> d9
        end

        purge --> prov --> t_pre --> conv --> reach --> bkphost --> t_term --> drill
        drill -.->|next variant round| purge
    end

    subgraph chaos["Chaos phase (against the last round's stack)"]
        seed["Seed a marker file on the app's NFS volume"]
        drain["Drain the worker running the app,<br/>forcing a reschedule to another node"]
        assertion["Assert the marker and reachability<br/>survived the reschedule"]
        seed --> drain --> assertion
    end

    teardown["Tear down: collect diagnostics + Playwright<br/>reports on failure, kill nodes, remove the lab network"]

    boot --> matrix --> chaos --> teardown

    classDef trigger fill:#f7e28b,stroke:#b8860b,color:#000
    class t_pre,t_term,t_d2,t_d4,t_d5 trigger
```

The nightly timers (volume 01:00, nfs 01:30, secrets 01:45, device
02:00, remote pull 00:30) run independently of every step above and
never fire during a lab run.

Scripts per step: bring-up [01_bootstrap.sh](01_bootstrap.sh) -
provision [02_provision_inventory.sh](02_provision_inventory.sh) -
converge [03_wait_converge.sh](03_wait_converge.sh) -
reachability [04_verify_reachable.sh](04_verify_reachable.sh) -
drill [backup/base.sh](backup/base.sh) -
marker [05_seed_content.sh](05_seed_content.sh) -
drain [06_drain_worker.sh](06_drain_worker.sh) -
assert [07_assert_state.sh](07_assert_state.sh) -
purge [../utils/clean/purge_stacks.sh](../utils/clean/purge_stacks.sh).
