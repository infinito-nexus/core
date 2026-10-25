---
name: i8-develop
description: >
  Develop a new feature, app, or larger change end to end. Use when no requirement file applies; otherwise prefer i8-requirement-implement. Infinito.Nexus specific.
routines:
  - develop
---

Follow the instructions from AGENTS.md, then develop the requested feature or app by following the `develop` routine exactly (run `python -m agents.routines show develop` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
