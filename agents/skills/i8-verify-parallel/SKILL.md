---
name: i8-verify-parallel
description: >
  Verify the branch from both ends at once: trigger the priority line through the i8-ci-trigger-priority skill, keep triaging that run on a loop, and iterate the same roles on the local stack in parallel. Infinito.Nexus specific.
routines:
  - verify_parallel
---

Follow the instructions from AGENTS.md, then run both verification lanes by following the `verify_parallel` routine exactly (run `python -m agents.routines show verify_parallel` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. The CI lane MUST be dispatched by invoking the `i8-ci-trigger-priority` skill rather than by building a line here, so the two skills cannot drift on what a verification row is. The two lanes run at once because they run on different machines; inside the local lane deploys stay serial. Never dispatch a second CI run while the triage loop is armed, and close each question by naming which lane answered it.
