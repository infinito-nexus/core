# Swarm Loop

Iterate on a swarm deploy of a role through Act and the `act-swarm-*` targets.
For the compose deploy of the same role, see [Compose Loop](compose.md).
For the cross-mode parity gate, see [Roundtrip Loop](roundtrip.md).
When Act aborts at "Set up job" on a recent Docker engine, see [Workflow Loop](workflow.md).

## Inspect before redeploy

An `act-swarm-zombie` run rebuilds a full DinD cluster over tens of minutes, so you MUST confirm a fix on the live cluster before redeploying.

- The run leaves the cluster up (`INFINITO_KEEP_SWARM_NODES=true`). You MUST reproduce the failure on it via `make act-swarm-exec` / `make act-swarm-shell`, then release it with `make act-swarm-down`.
- You MAY confirm an early-stage fix (config render, realm import) while the run is still going.
- In-cluster edits are validation only. You MUST apply the real fix in the repository before the next redeploy.
- You MUST NOT commit during an active iteration, because a live deploy makes the pre-commit hook stash the files it reads. If a commit is unavoidable, you MUST pass `--no-verify`.
- For failures the cluster cannot show (app discovery, render-time lookups, multi-node placement), you MUST say so instead of faking an in-cluster check.

## NFS server flavor

The swarm-test nfs-server serves shared storage from userspace `nfs-ganesha` (the `ganesha` flavor of `svc-storage-nfs-server`, selected when `RUNTIME in ['dev', 'act']`), because the kernel `nfsd` is not network-namespaced and a privileged DinD node driving it would wedge `exportfs` into a D-state.
If a swarm step hangs at `Reload NFS exports` from a stuck kernel-NFS mount, you MUST recover with `make act-swarm-clean` on the host; see the NFS gotcha in [Roundtrip Loop](roundtrip.md).
You MUST NOT fall back to a compose-only sweep while swarm is blocked.
