# 087 - Agents Phase 10: SaaS Integration and Local End to End

## User Story

As an operator, I want the agents bundle deployed together with every app of the deploy matrix and the agents' end-to-end chains proven locally through act with local models only, so that the first CI deploy of `feature/agents` starts from a stack that is already green on the developer machine.

## Scope

- Phase 10 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 6 of its iteration plan. The Local setup and integration workflows, Verification and Iteration plan sections of 089 apply.
- Builds on: `inventories/bundles/servers/agents/`, `.github/workflows/call-test-agents-saas.yml`, `.github/workflows/cron-test-agents-saas.yml`, `scripts/agents/integration.sh` and every earlier phase.
- Gate: `make agents-verify` and `make agents-integration` are green locally in compose mode.
- Depends on: [085](085-agents-phase-8-remote-and-detached.md) and [086](086-agents-phase-9-ai-role-cleanup.md).

## Acceptance Criteria

### Local setup and integration workflows

- [ ] `inventories/bundles/servers/agents/` deploys the complete agent infrastructure against localhost with `make compose-deploy`, and its README describes how.
- [ ] `call-test-agents-saas.yml` deploys every app of the `call-test-deploy.yml` matrix together with the agents bundle, runs every Playwright spec of the deployed app and every agent scenario with local models only; the CI runs the matrix in parallel, and `make agents-integration` runs the same file through act one app after the other.
- [ ] `call-test-agents-saas.yml` runs nightly and on manual dispatch, and is a required check before `feature/agents` merges into `main`; phase pull requests into `feature/agents` are gated only by their own criteria.
- [ ] No request of a `call-test-agents-saas.yml` run reaches an external model provider (gateway log).
- [ ] Only the end-to-end scenarios, the `judge_answers` negative control and the Claude Code path call a live model, and that model supports tool calling.

### End to end

- [ ] `make agents-verify` and `make agents-integration` are green locally in compose mode before the first CI deploy of `feature/agents`.
- [ ] The maintainer fixes a seeded failing test from a failed run through to an open pull request without human input.
- [ ] The designer opens a pull request that changes the design of one app, with before and after gallery.
- [ ] The tuner opens a pull request with a measured performance improvement, carrying a before and after number from the same source and image and load state.
- [ ] The implementer turns an `Approved` work package into an open pull request.
- [ ] A full chain runs without manual steps between the agents: support ticket -> planner work package -> human approval -> implementer pull request -> reviewer recommendation -> human merge -> release draft.
- [ ] The hacker files a report and sends an email against the running verification stack, and the maintainer picks the report up as a fix.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
