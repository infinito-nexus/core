---
name: i8-iterate-runner
description: >
  Iterate on the Infinito.Nexus svc-runner role or the self-hosted CI runner
  infrastructure (registration, configuration, nested deploy). Use when working
  on svc-runner, runner registration, or the runner's nested deploy path.
  Infinito.Nexus specific.
routines:
  - iterate_runner
---

Follow the instructions from AGENTS.md, then follow the `iterate_runner` routine exactly (run `python -m agents.routines show iterate_runner` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.

When the runner pool serves the deploy (`INFINITO_DEPLOY_VIA_POOL=true`), every deploy of the iteration runs with `hold=true`, the iteration works against that held job stack through `job=<id>`, and it ends with `make runner-release job=<id>`.
