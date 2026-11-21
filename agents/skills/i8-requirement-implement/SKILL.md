---
name: i8-requirement-implement
description: >
  Implement an existing requirement file end to end. Run i8-requirement-create first if none exists yet. Infinito.Nexus specific.
routines:
  - requirements
---

Follow the instructions from AGENTS.md, then implement the given requirement file by following the `requirements` routine exactly (run `python -m agents.routines show requirements` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
