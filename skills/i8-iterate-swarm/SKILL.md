---
name: i8-iterate-swarm
description: >
  Iterate on an Infinito.Nexus swarm deploy of a role through Act and the swarm-*
  make targets. Use when iterating, debugging, or redeploying a role in swarm
  mode, when an act-swarm run fails, or before any swarm redeploy. Infinito.Nexus
  specific.
---

Follow the instructions from AGENTS.md, then follow the procedure in `docs/agents/action/iteration/swarm.md` (relative to the Infinito.Nexus repository root) exactly. That document is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Completion gate: the role is green end-to-end in swarm; for a full web-app change also drive it through compose via the `i8-iterate-compose` skill until green in BOTH modes.
