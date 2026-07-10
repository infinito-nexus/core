# Roundtrip Loop

Use this page for validating one or more roles across **every deploy mode in order** (compose, then swarm) as a breadth-first cross-mode parity gate, rather than a focused single-mode debug session.
For debugging the compose deploy of one role, see [Compose Loop](compose.md); for the swarm / Act side, see [Swarm Loop](swarm.md); for spec-level inner-loop iteration, see [Playwright Spec Loop](playwright.md).

## When to use

- Use the roundtrip loop to **confirm parity**: a role (or a set of roles) must come up green in compose AND swarm. It is the end-of-change regression sweep, not the place to debug a fresh failure.
- While you are actively debugging one mode, use the focused loops instead: [Compose Loop](compose.md) for the compose deploy, [Swarm Loop](swarm.md) plus the `swarm-*` targets for the swarm deploy. Return to the roundtrip once both modes pass in isolation.

## The loop

- Invoke with `make roundtrip apps="<app> [app...]"`. Each app is taken through the mode sequence in order, and the run stops at the first failure (fail-fast).
- With no `apps=`, the loop defaults to **every application, most-complex first** (the `complexity` CLI: `infinito meta roles applications complexity --sort "desc weight" --format string`). That is a large run (one compose plus one swarm deploy per app), so narrow it with `apps=` while iterating.
- The mode sequence defaults to `compose swarm` and is overridable with `modes="compose swarm"`. The order is always compose first, so the cheaper mode fails fast before the expensive swarm rebuild. Append `k8s` here once that mode exists.
- Per step the output is streamed to `${TMPDIR:-/tmp}/roundtrip-<app>-<mode>.log`. Tell the operator the exact `tail -f` path for the running step.
- The compose step runs `compose-deploy mode=reinstall apps=<app> full_cycle=true variant=0`; the swarm step runs `swarm-zombie app=<app>`, pinned to `variant:0` so a multi-variant app validates one cluster (parity with the compose step, not the full per-variant CI matrix that runs one isolated runner per variant). The cluster is named `<app>-swarm-mgr-01` etc. via the mandatory `SWARM_NAME` (the app id is the default cluster id). Each validated swarm cluster is released afterwards unless you pass `keep=true`.
- `make autoformat` and `make test` MUST be green before a roundtrip; the loop does not re-run them per app.
- **A blocked mode is NEVER a reason to silently switch to another.** If a mode cannot run (the swarm NFS wedge below, a wedged daemon, a missing host capability), STOP the whole sweep, report the blocker together with the exact recovery command, and wait for it to be cleared. You MUST NOT fall back to a `modes=compose`-only (or any reduced) sweep to look productive: it hides the unmet swarm parity and never satisfies the compose-AND-swarm gate. Resume the full sweep only once the blocker is gone.

## Inspect before redeploy

The roundtrip is a gate, not a debugger: when a step goes red it stops and leaves the evidence in place. Do NOT just re-run the roundtrip; drop into the matching focused loop.

- Read `${TMPDIR:-/tmp}/roundtrip-<app>-<mode>.log` to see which app and mode failed, and the first error.
- If the **compose** step failed, switch to the [Compose Loop](compose.md): reproduce with `make compose-deploy mode=update apps=<app>`, inspect via `make compose-exec` / `make compose-inner-run`, apply the real fix in the repository, then re-run the roundtrip.
- If the **swarm** step failed, the cluster is left up (fail-fast skips the release). Inspect it with `make swarm-exec node=<app>-swarm-mgr-01 cmd='...'` or `make swarm-shell name=<app>` per the [Swarm Loop](swarm.md), confirm the fix on the live cluster, then re-run. Release it manually with `make swarm-down name=<app>` when done.
- Validate every candidate fix on live state BEFORE the next roundtrip; a swarm rebuild costs tens of minutes (same rule as the focused loops). In-cluster edits are validation only, the repo change is the real fix.

## Exit

- Once the failing mode is green in its focused loop, you MUST resume the roundtrip over the failed app plus the apps that have not run yet (`apps="<failed-app> <still-untested apps in complexity order>"`), and you MUST NOT restart the full sweep from the top. Apps that already went green earlier in the same run stay green; re-running them wastes one swarm rebuild each.
- You MUST re-run the full no-`apps=` sweep only as the final end-to-end parity confirmation, after the tail has gone green.

## Recovery & gotchas

- On a recent Docker engine the swarm step can abort at job setup; run `make act-runner-image` once and prefix the run with `ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest` (see [Workflow Loop](workflow.md)).
- The swarm-test nfs-server serves shared storage from userspace `nfs-ganesha` (the `ganesha` flavor of `svc-storage-nfs-server`, selected when `RUNTIME in ['dev', 'act']`), which runs inside the privileged DinD node and never touches the host kernel `nfsd`, so an interrupted export cannot wedge the host. Production keeps the `kernel` flavor on real hosts, where `nfsd` is not shared across clusters. If a swarm step ever hangs at `Reload NFS exports` from a stuck kernel-NFS mount, you MUST recover with `make swarm-clean` on the host (needs sudo): it removes what the docker CLI can, then runs `umount -f -l /var/lib/infinito` + `exportfs -ua` + `systemctl restart docker`. The no-sudo sandbox only prints those commands, so the host recovery is mandatory and the sweep MUST stop until it is done; never fall back to compose-only.
- Distinct `SWARM_NAME` per app means several apps can keep their clusters in parallel under `keep=true`; release each one with `make swarm-down name=<app>`.
