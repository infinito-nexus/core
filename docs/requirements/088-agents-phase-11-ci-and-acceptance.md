# 088 - Agents Phase 11: CI on Core, Final Acceptance and Board Migration

## User Story

As an operator, I want the agents restructuring proven by the CI on `infinito-nexus/core`, accepted with my own credentials, and the requirements migrated to the OpenProject board as the last step, so that `feature/agents` merges into `main` with every criterion backed by a recorded proof.

## Scope

- Phase 11 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 7 of its iteration plan plus the board migration it orders last. The Verification, Lint tests and Iteration plan sections of 089 apply.
- The criteria below are moved from 089 unchanged: "this one" and "this file" in them mean 089.
- Builds on: every earlier phase, `agents/criteria.yml` and the lints L22 and L23.
- Gate: the CI pipeline of `feature/agents` on `infinito-nexus/core` is green with every scenario id in its job log; the board migration runs after every other criterion is checked.
- Depends on: [087](087-agents-phase-10-saas-integration.md).

## Acceptance Criteria

### Board

- [ ] Every open requirement under `docs/requirements/`, including this one, exists as an OpenProject work package with its acceptance criteria as checklist, migrated after every other criterion of this file and after the requirement hygiene criteria are green.
- [ ] `docs/requirements/` is deleted, and `docs/contributing/requirements.md` and the `i8-requirement-*` skills describe and use the OpenProject API.
- [ ] The lints that read `docs/requirements/` are removed or retargeted to `agents/criteria.yml`, and no lint needs the board to be reachable.

### Security controls

- [ ] CI runs triggered by an agent's fork pull request see no repository secret and no write token.

### Lint tests

- [ ] The repository as delivered passes every lint of the catalog.

### Local setup and integration workflows

- [x] `agents/criteria.yml` maps every criterion id to its proof kind and its proof; a lint fails on a criterion without a proof, on a proof without a criterion, and on a criterion whose wording asks for a probe, a refusal, a time bound or a restart but whose proof is not a scenario.
  - Evidence: `tests/lint/agents/test_l22_criteria_map.py` fails a criterion without an existing proof and a probe, refusal, time or restart wording without a scenario; `tests/lint/agents/test_l22_criteria_map.py` fails a scenario under `agents/scenarios/` or a catalog lint under `tests/lint/agents/` that no criterion claims, and a scenario whose `criterion` field names another one; red fixtures at `tests/lint/agents/test_l22_criteria_map.py`; `agents/criteria.yml` now also maps L22 and L23.
- [x] Every lint and unit proof has a fixture that turns it red, and the red run is recorded.
  - Evidence: `tests/lint/agents/test_l23_red_fixtures.py` fails any `lint` or `unit` proof of `agents/criteria.yml` without a red fixture; every one of them, the two unit proofs `UT-TRANSLATOR-ENGINE-MARK` and `UT-TRANSLATE-STRATEGY` included, records its red run as a `test_red_fixture_*` test that asserts the broken input fails.

### End to end

- [ ] Every new and changed role is green in compose and in swarm.
- [ ] Every swarm criterion is proven by a CI run on `infinito-nexus/core`, with the job-log line where the change ran recorded in `agents/criteria.yml`.
- [ ] The scenarios that need external credentials (GitHub per role, Anthropic `api_key` and `subscription`) pass in a final run with the operator's credentials.
- [ ] The CI pipeline of `feature/agents` is green with the agent scenarios executed (each scenario id present in the job log).

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
