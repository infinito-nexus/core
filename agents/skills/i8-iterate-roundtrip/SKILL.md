---
name: i8-iterate-roundtrip
description: >
  Validate one or more Infinito.Nexus roles across both deploy modes in order
  (compose then swarm) as a cross-mode parity gate. Use for a breadth-first
  regression sweep confirming a role comes up green in compose AND swarm, not for
  debugging a fresh single-mode failure. Infinito.Nexus specific.
routines:
  - iterate_roundtrip
---

Follow the instructions from AGENTS.md, then follow the `iterate_roundtrip` routine exactly (run `python -m agents.routines show iterate_roundtrip` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Every 15 minutes verify the container is still running and not hanging. Done only when every role is green in compose AND swarm.
