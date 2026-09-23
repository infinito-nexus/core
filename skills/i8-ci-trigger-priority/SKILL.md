---
name: i8-ci-trigger-priority
description: >
  Lead a manual CI run with a priority line that verifies the branch's still-open questions: up to 20 selections, every axis chosen by measured runtime, workspace and chunk gate off. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then build and dispatch the priority line by following the
procedure in `docs/agents/action/ci-trigger-priority.md` (relative to the Infinito.Nexus repository root)
exactly. That document is the source of truth; this skill only routes you
there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Never dispatch a line the validator refuses, and report per candidate which axis was pinned and which question the run will not answer.
