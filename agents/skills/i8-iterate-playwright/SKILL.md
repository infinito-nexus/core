---
name: i8-iterate-playwright
description: >
  Inner-loop iteration on an Infinito.Nexus role-local playwright.spec.js against
  an already-running stack without redeploying (make compose-playwright /
  swarm-playwright). Use when writing, debugging, or fixing a Playwright spec for
  a web-* role. Infinito.Nexus specific.
routines:
  - iterate_playwright
---

Follow the instructions from AGENTS.md, then follow the `iterate_playwright` routine exactly (run `python -m agents.routines show iterate_playwright` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `kvb-think-listen` skill (escalating any root-cause or design question you are not ~99% sure of to the `kvb-think-dialectic` skill), then work under the `kvb-org-robot` skill. Ask upfront whether to scope changes to the Playwright spec files only, or also to any other files that cause the tests to fail.

When the runner pool serves the deploy (`INFINITO_DEPLOY_VIA_POOL=true`), every deploy of the iteration runs with `hold=true`, the iteration works against that held job stack through `job=<id>`, and it ends with `make runner-release job=<id>`.
