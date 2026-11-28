---
name: i8-push-trigger-pull
description: >
  Push a branch, run it through the manual-CI draft cycle, and transition the PR to ready-for-review. Infinito.Nexus specific.
routines:
  - push_trigger_pull
---

Follow the instructions from AGENTS.md, then push the branch, run the manual-CI draft cycle, and transition the PR to ready-for-review by following the `push_trigger_pull` routine exactly (run `python -m agents.routines show push_trigger_pull` to print its ordered steps). That routine is the source of truth; this skill only routes you there. A new draft's body is rendered from the one template through `python -m cli.contributing.pull_request render`, with the score block as the `kvb-check-score` `--table` output; the contract is in `docs/contributing/artefact/git/pull-request.md`. Begin by clarifying every open requirement with the `kvb-think-listen` skill (escalating any root-cause or design question you are not ~99% sure of to the `kvb-think-dialectic` skill), then work under the `kvb-org-robot` skill.
