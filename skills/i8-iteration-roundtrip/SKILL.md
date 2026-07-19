---
name: i8-iteration-roundtrip
description: >
  Validate one or more Infinito.Nexus roles across both deploy modes in order
  (compose then swarm) as a cross-mode parity gate. Use for a breadth-first
  regression sweep confirming a role comes up green in compose AND swarm, not for
  debugging a fresh single-mode failure. Infinito.Nexus specific.
---

Follow the procedure in `docs/agents/action/iteration/roundtrip.md` (relative to
the Infinito.Nexus repository root) exactly. That document is the source of
truth; this skill only routes you there.
