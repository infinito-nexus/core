---
name: i8-worktree-create
description: >
  Check a branch out into an isolated parallel worktree with its own slot,
  subnet, ports and container names (make worktree-up). Trigger whenever a
  second branch needs a working copy alongside the primary checkout, for
  example to run two deploys at once. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then run
`make worktree-up branch=<branch>` (the default action of this skill). The
worktree lands under `~/.local/share/worktrees/<domain>/<account>/<repo>/<branch>`
and joins the primary checkout's cache stack instead of starting its own.

The branch MUST exist and MUST NOT be checked out anywhere else; resolve a
collision with `make worktree-prune` or `make worktree-down` first. Pass
`base=<dir>` only when the operator names a different parent directory, and
then repeat that same `base=` in every later `make worktree-down` call.

Report the slot, path, subnet, bind IP and container name from the target's
summary, and hand the operator the `cd <path>` plus `make compose-up` follow-up.

Begin by clarifying every open requirement with the `active-listening` skill,
then work under the `robot` skill. The task is finished only when the worktree
exists and its `.env` has been generated.
