---
name: i8-debug-ci
description: >
  Turn a failed CI run into a grouped, root-caused fix plan. Infinito.Nexus
  specific.
routines:
  - debug_ci
---

Download the failed run's job logs, group the failing jobs by their failing
log line, find the root cause and failure class per cluster, and produce a fix
plan with its evidence or escalate an infra fault. The deterministic steps and
the order are the `debug_ci` routine; see
`python -m agents.routines show debug_ci`. Escalate any root-cause you are not
about 99 percent sure of to the `dialectic` skill.
