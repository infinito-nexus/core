---
name: i8-push-trigger-pull
description: >
  Push a branch, run it through the manual-CI draft cycle, and transition the PR to ready-for-review. Infinito.Nexus specific.
routines:
  - push_trigger_pull
---

Follow the instructions from AGENTS.md, then push the branch, run the manual-CI draft cycle, and transition the PR to ready-for-review by following the `push_trigger_pull` routine exactly (run `python -m agents.routines show push_trigger_pull` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.
