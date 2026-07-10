# Swarm Loop

Iterate on a swarm deploy of a role through Act and the `swarm-*` targets.
For the compose deploy of the same role, see [Compose Loop](compose.md).
For the cross-mode parity gate, see [Roundtrip Loop](roundtrip.md).
When Act aborts at "Set up job" on a recent Docker engine, see [Workflow Loop](workflow.md).

## When to use

- Use this loop while actively iterating on or debugging the swarm deploy of a single role through `swarm-zombie` and the `swarm-*` targets.
- For the compose deploy of the same role use the [Compose Loop](compose.md); for the compose-then-swarm parity gate use the [Roundtrip Loop](roundtrip.md).

## The loop

- `swarm-zombie app=<app>` builds a full DinD cluster and leaves it up (`INFINITO_KEEP_SWARM_NODES=true`) for inspection.
- Inspect the live cluster with `make swarm-exec` / `make swarm-shell`, then release it with `make swarm-down`.
- Apply the real fix in the repository, then rebuild with a new `swarm-zombie` run.

## Inspect before redeploy

An `swarm-zombie` run rebuilds a full DinD cluster over tens of minutes, so you MUST confirm a fix on the live cluster before redeploying.

- Before every redeploy you MUST fully resolve the failure in swarm and reach at least **95% confidence that your fix actually fixes it**. That confidence MUST come from inspecting the live cluster in-container: reproduce the failure, walk the fix path, and confirm the corrected behaviour on the running services. Never redeploy on a guess — a swarm redeploy costs tens of minutes.
- The run leaves the cluster up (`INFINITO_KEEP_SWARM_NODES=true`). You MUST reproduce the failure on it via `make swarm-exec` / `make swarm-shell`, then release it with `make swarm-down`.
- You MAY confirm an early-stage fix (config render, realm import) while the run is still going.
- In-cluster edits are validation only. You MUST apply the real fix in the repository before the next redeploy.
- You MUST NOT commit during an active iteration, because a live deploy makes the pre-commit hook stash the files it reads. If a commit is unavoidable, you MUST pass `--no-verify`.
- For failures the cluster cannot show (app discovery, render-time lookups, multi-node placement), you MUST say so instead of faking an in-cluster check.
- When it helps isolate a swarm-only failure from a shared one, you MAY bring up the compose deploy of the same role in parallel (see [Compose Loop](compose.md)) purely for comparison and inspection.

## Recovery & gotchas

### NFS server flavor

The swarm-test nfs-server uses the userspace `nfs-ganesha` (`ganesha`) flavor for local runtimes (`RUNTIME in ['dev', 'act']`) and the `kernel` flavor for real GitHub Actions CI and production, so CI exercises the production flavor. Kernel `nfsd` in a privileged DinD node is wedge-prone: the export can be present yet the controller mount returns ENOENT, and `exportfs` can stick in D-state.
If a swarm step hangs at `Reload NFS exports` from a stuck kernel-NFS mount, you MUST recover with `make swarm-clean` on the host; see the NFS gotcha in [Roundtrip Loop](roundtrip.md).
You MUST NOT fall back to a compose-only sweep while swarm is blocked.
