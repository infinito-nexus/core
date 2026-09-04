---
name: i8-worktree-down
description: >
  Stop a branch worktree's compose stack, release its checkout and free its
  slot (make worktree-down). Trigger when a parallel worktree is no longer
  needed or when its branch is blocked as already checked out. Infinito.Nexus
  specific.
---

Follow the instructions from AGENTS.md, then run
`make worktree-down branch=<branch>` (the default action of this skill). Pass
the same `base=<dir>` that `make worktree-up` was given, otherwise the target
looks in the default parent directory and reports no worktree at that path.

The target refuses to drop a worktree with uncommitted changes. Show the
operator that status and let them decide; only add `force=true` when they
explicitly ask for it, because it discards the changes.

When the checkout is already gone but the branch is still held, run
`make worktree-prune` instead.

Begin by clarifying every open requirement with the `active-listening` skill,
then work under the `robot` skill. The task is finished only when the slot is
reported as released and the branch is checkable out again.
