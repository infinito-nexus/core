---
name: i8-quality
description: >
  Run the project quality gate (make quality: autoformat plus the full test and
  lint suite) and drive it to green. Trigger before a commit or deploy, or
  whenever the operator asks to check quality. Infinito.Nexus specific.
routines: []
---

Follow the instructions from AGENTS.md, then run `make quality` (the default
action of this skill). Stream the output to a log under `/tmp` and iterate: read
the per-target result table, not the pipe exit code (which is unreliable), fix
every failure at its root, and re-run until `make quality` is green end to end.

The gate runs in the shared test runner `infinito-test-<hash>` of this checkout's toolchain image, with the checkout as working directory, and starts no deploy stack (`coredns`, `infinito`, `target`, `target-resolver`).
The first test or lint call on the machine starts that runner, and every later call from a checkout with the same image reuses it.
`make test-runner-status` shows the runner, whether it runs and the worktree roots it mounts; `make test-runner-down` removes it, and the next call starts a new one.
With `INFINITO_STACK_NAME` set, the gate runs in that stack's `infinito` container instead.

Begin by clarifying every open requirement with the `kvb-think-listen` skill
(escalating any root-cause or design question you are not ~99% sure of to the
`kvb-think-dialectic` skill), then work under the `kvb-org-robot` skill. The gate is finished only
when `make quality` passes clean.
