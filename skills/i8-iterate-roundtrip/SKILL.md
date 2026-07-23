---
name: i8-iterate-roundtrip
description: >
  Validate one or more Infinito.Nexus roles across both deploy modes in order
  (compose then swarm) as a cross-mode parity gate. Use for a breadth-first
  regression sweep confirming a role comes up green in compose AND swarm, not for
  debugging a fresh single-mode failure. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then follow the procedure in `docs/agents/action/iteration/roundtrip.md` (relative to the Infinito.Nexus repository root) exactly. That document is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Every 15 minutes verify the container is still running and not hanging. Done only when every role is green in compose AND swarm.
