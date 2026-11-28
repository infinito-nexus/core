---
name: i8-worktree-create
description: >
  Check a branch out into an isolated parallel worktree with its own slot,
  subnet, ports and container names (make worktree-up). Trigger whenever a
  second branch needs a working copy alongside the primary checkout, for
  example to run two deploys at once. Infinito.Nexus specific.
routines: []
---

Follow the instructions from AGENTS.md, then run
`make worktree-up branch=<branch>` (the default action of this skill). The
worktree lands under `~/.local/share/worktrees/<domain>/<account>/<repo>/<branch>`.
It gets no cache network and no cache address: every checkout reaches the
caches and the tools of the machine-wide infra runner by name on the network
`infinito-infra`. A worktree outside `INFINITO_WORKTREE_ROOTS` is invisible to
the infra runner and the shared test runner.

The branch MUST exist and MUST NOT be checked out anywhere else; resolve a
collision with `make worktree-prune` or `make worktree-down` first. Pass
`base=<dir>` only when the operator names a different parent directory, and
then repeat that same `base=` in every later `make worktree-down` call.

Report the slot, path, subnet, bind IP and container name from the target's
summary, and hand the operator the `cd <path>` follow-up. Tests and lints need
no stack, because they run in the shared test runner; name `make compose-up`
only when the worktree is meant to deploy.

Begin by clarifying every open requirement with the `kvb-think-listen` skill,
then work under the `kvb-org-robot` skill. The task is finished only when the worktree
exists and its `.env` has been generated.
