---
name: i8-iterate-playwright
description: >
  Inner-loop iteration on an Infinito.Nexus role-local playwright.spec.js against
  an already-running stack without redeploying (make compose-playwright /
  swarm-playwright). Use when writing, debugging, or fixing a Playwright spec for
  a web-* role. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then follow the procedure in `docs/agents/action/iteration/playwright.md` (relative to the Infinito.Nexus repository root) exactly. That document is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Ask upfront whether to scope changes to the Playwright spec files only, or also to any other files that cause the tests to fail.
