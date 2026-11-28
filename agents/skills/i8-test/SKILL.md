---
name: i8-test
description: >
  Run and validate the test suite for a given scope. Infinito.Nexus specific.
routines:
  - testing
---

Follow the instructions from AGENTS.md, then run and validate tests for the requested scope by following the `testing` routine exactly (run `python -m agents.routines show testing` to print its ordered steps). That routine is the source of truth; this skill only routes you there. Begin by clarifying every open requirement with the `kvb-think-listen` skill (escalating any root-cause or design question you are not ~99% sure of to the `kvb-think-dialectic` skill), then work under the `kvb-org-robot` skill.

Every `make test*` and `make lint*` target runs in the shared test runner `infinito-test-<hash>` of this checkout's toolchain image and starts no deploy stack; `make test-runner-status` shows it and `make test-runner-down` removes it. A deploy with `hold=true` keeps its pool job's stack until the iteration ends, so release it with `make runner-release job=<id>`, the id printed by `make runner-status`.
