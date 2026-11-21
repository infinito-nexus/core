---
name: i8-debug-local
description: >
  Debug a local deploy that is failing on the host. Infinito.Nexus specific.
routines:
  - debug_local
---

Follow the instructions from AGENTS.md, then debug the failing local deploy of the given role by following the `debug_local` routine exactly (run `python -m agents.routines show debug_local` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
