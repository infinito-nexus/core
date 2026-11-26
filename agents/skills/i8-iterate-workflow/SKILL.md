---
name: i8-iterate-workflow
description: >
  Iterate on Infinito.Nexus GitHub Actions workflows locally through Act. Use
  when debugging or editing a CI workflow, running act, or when a make swarm-* or
  act-* target aborts at "Set up job" on a recent Docker engine. Infinito.Nexus
  specific.
routines:
  - iterate_workflow
---

Follow the instructions from AGENTS.md, then follow the `iterate_workflow` routine exactly (run `python -m agents.routines show iterate_workflow` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill.

When the runner pool serves the deploy (`INFINITO_DEPLOY_VIA_POOL=true`), every deploy of the iteration runs with `hold=true`, the iteration works against that held job stack through `job=<id>`, and it ends with `make runner-release job=<id>`.
