---
name: i8-iterate-swarm
description: >
  Iterate on an Infinito.Nexus swarm deploy of a role through Act and the swarm-*
  make targets. Use when iterating, debugging, or redeploying a role in swarm
  mode, when an act-swarm run fails, or before any swarm redeploy. Infinito.Nexus
  specific.
routines:
  - iterate_swarm
---

Follow the instructions from AGENTS.md, then follow the `iterate_swarm` routine exactly (run `python -m agents.routines show iterate_swarm` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Completion gate: the role is green end-to-end in swarm; for a full web-app change also drive it through compose via the `i8-iterate-compose` skill until green in BOTH modes.
