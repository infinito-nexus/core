---
name: i8-worktree-down
description: >
  Stop a branch worktree's compose stack, release its checkout and free its
  slot (make worktree-down). Trigger when a parallel worktree is no longer
  needed or when its branch is blocked as already checked out. Infinito.Nexus
  specific.
routines: []
---

Follow the instructions from AGENTS.md, then run
`make worktree-down branch=<branch>` (the default action of this skill). Pass
the same `base=<dir>` that `make worktree-up` was given, otherwise the target
looks in the default parent directory and reports no worktree at that path.

The target stops only the worktree's own deploy stack. A pool job this worktree
submitted with `hold=true` keeps its stack on the infra runner's daemon, so list
the held jobs with `make runner-status` and release each of them with
`make runner-release job=<id>`. It never stops the
machine-wide infra runner (`infinito-infra`), the runner pool or a shared test
runner `infinito-test-<hash>`: other checkouts keep using them, and nothing of
the caches or the tools belongs to one worktree.

The target refuses to drop a worktree with uncommitted changes. Show the
operator that status and let them decide; only add `force=true` when they
explicitly ask for it, because it discards the changes.

When the checkout is already gone but the branch is still held, run
`make worktree-prune` instead.

Begin by clarifying every open requirement with the `kvb-think-listen` skill,
then work under the `kvb-org-robot` skill. The task is finished only when the slot is
reported as released and the branch is checkable out again.
