---
name: i8-quality
description: >
  Run the project quality gate (make quality: autoformat plus the full test and
  lint suite) and drive it to green. Trigger before a commit or deploy, or
  whenever the operator asks to check quality. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then run `make quality` (the default
action of this skill). Stream the output to a log under `/tmp` and iterate: read
the per-target result table, not the pipe exit code (which is unreliable), fix
every failure at its root, and re-run until `make quality` is green end to end.

Begin by clarifying every open requirement with the `active-listening` skill
(escalating any root-cause or design question you are not ~99% sure of to the
`dialectic` skill), then work under the `robot` skill. The gate is finished only
when `make quality` passes clean.
