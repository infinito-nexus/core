---
name: i8-debug-log
description: >
  Inspect a *.log or job-logs file the operator dropped in the workdir. Infinito.Nexus specific.
routines:
  - debug_log
---

Follow the instructions from AGENTS.md, then inspect the given log file by following the `debug_log` routine exactly (run `python -m agents.routines show debug_log` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
