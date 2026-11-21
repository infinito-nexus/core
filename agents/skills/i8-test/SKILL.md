---
name: i8-test
description: >
  Run and validate the test suite for a given scope. Infinito.Nexus specific.
routines:
  - testing
---

Follow the instructions from AGENTS.md, then run and validate tests for the requested scope by following the `testing` routine exactly (run `python -m agents.routines show testing` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
