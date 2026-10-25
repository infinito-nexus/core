---
name: i8-pull-request
description: >
  Open a pull request for the current branch. Infinito.Nexus specific.
routines:
  - pull_request
---

Follow the instructions from AGENTS.md, then open a pull request for the current branch by following the `pull_request` routine exactly (run `python -m agents.routines show pull_request` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
