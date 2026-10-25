---
name: i8-iterate-compose
description: >
  Iterate on an Infinito.Nexus role via the local compose deploy/test loop
  (make compose-deploy). Use when iterating, debugging, or redeploying a single
  role in compose mode, when a local compose deploy fails, or before any compose
  redeploy. Infinito.Nexus specific.
routines:
  - iterate_compose
---

Follow the instructions from AGENTS.md, then follow the `iterate_compose` routine exactly (run `python -m agents.routines show iterate_compose` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Begin by clarifying every open requirement with the `active-listening` skill (escalating any root-cause or design question you are not ~99% sure of to the `dialectic` skill), then work under the `robot` skill. Completion gate: the role is green end-to-end in compose; for a full web-app change also drive it through swarm via the `i8-iterate-swarm` skill until green in BOTH modes.

Default `disable=matomo,dashboard,prometheus,email,css`. One `mode=update apps=<roles> purge=true` tests app-state involvement, then back to `mode=update`.

## Matrix-variant commands

Do not improvise `mode`/`variant`; pick the row:

| Situation | `make compose-deploy` args |
|---|---|
| Baseline, once before any edit | `mode=reinstall apps=<roles> full_cycle=true` (no variant) |
| Variant `<idx>` failed, code changed | `mode=update apps=<roles> variant=<idx>` (loop until green) |
| Variant `<idx>` not yet deployed vs current code | `mode=reinstall apps=<roles> full_cycle=true variant=<idx>` |
| Final gate, once every variant green | `mode=reinstall apps=<roles> full_cycle=true` (no variant) |

FORBIDDEN: a bare `mode=update` without `variant=` on a matrix-variant role; a no-variant `mode=reinstall` as reaction to a failed variant or a code change.

## Pre-redeploy gate

After a failed deploy, before every redeploy, emit exactly one:
- `verified-in-container: <command> → <observed success>`
- `post-deploy-state-exception: <multi-container/persistent/post-hook state that genuinely cannot be reproduced in the live container>`

The redeploy is never the verification. Not valid excuses: reset is fiddly, fix was logically inferred, change looks obviously correct.
