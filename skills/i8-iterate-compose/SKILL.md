---
name: i8-iterate-compose
description: >
  Iterate on an Infinito.Nexus role via the local compose deploy/test loop
  (make compose-deploy). Use when iterating, debugging, or redeploying a single
  role in compose mode, when a local compose deploy fails, or before any compose
  redeploy. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then follow the procedure in `docs/agents/action/iteration/compose.md` (relative to the Infinito.Nexus repository root) exactly. That document is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Completion gate: the role is green end-to-end in compose; for a full web-app change also drive it through swarm via the `i8-iterate-swarm` skill until green in BOTH modes.
