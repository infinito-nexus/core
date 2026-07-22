---
name: i8-requirement-create
description: >
  Write a new requirement file. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then create a new requirement for the given topic by following the
procedure in `docs/contributing/requirements.md` (relative to the Infinito.Nexus repository root)
exactly. That document is the source of truth; this skill only routes you
there. Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Before every redeploy you MUST run `make compose-exec` and `make compose-inner-run` against the live stack and fully fix and inspect every failure in the container. A new deploy iteration MUST NOT start until every error is resolved and the fix has been empirically verified in-container. The iteration is finished only when every role is green end to end.
