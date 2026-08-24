---
name: i8-merge-sibling
description: >
  Pull a sibling feature branch and merge it into the current one, resolving
  conflicts by combining both sides' intent rather than picking a side, then
  prove the result with make quality before the merge commit. Use whenever the
  operator asks to pull and merge another branch. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then run the sequence below. The branch
to merge is the skill argument; default to `feature/swarm-nfs` when none is given.

## Before touching the tree

Never start while a sweep, deploy, or gate is reading the working tree — a merge
swaps files under it and has already destroyed a running roundtrip once. Stop the
run first or wait for it. Untracked leftovers from an aborted merge block the next
attempt: verify each against `git ls-tree -r --name-only FETCH_HEAD` before
deleting, then delete them, and do not start a second in-sandbox attempt that
recreates them.

## Sequence

Fetch with `git fetch fork <branch>`, list what is incoming, then merge
`FETCH_HEAD`. Resolve every conflict, run `make quality`, fix what it reports,
and re-run until all four targets are green. Leave the merge commit to the
operator unless they asked for it.

## Conflict doctrine

Neither side wins by default. Decide per hunk:

- Additive lists (dependencies, ignores, aliases) take the **union**; do not
  reorder beyond what the merge requires.
- Behaviour-equal alternatives take the side that routes through the SPOT
  variable instead of inlining the expression again.
- Where this branch's lint enforces a convention (`gotoOnion`, `resolveTimeout`,
  `nocheck` markers for `|| true`), that convention is non-negotiable — keep it
  and adopt the incoming side's structure around it.
- Where the two differ in semantics, take the one that fails loudly: an absent
  return code is a failure, not a success.
- A block that only one side has is usually a feature the other never had. Check
  whether it was superseded before dropping it — grep for its variables.

State per conflict which side won and why; a reader must be able to audit the
judgement without reopening the diff.
