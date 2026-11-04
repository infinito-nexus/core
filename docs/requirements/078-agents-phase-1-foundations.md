# 078 - Agents Phase 1: Foundations and Static Routine Layer

## User Story

As an operator, I want the `agents/` tree, the lint catalog and the deterministic routine layer of the agent platform to be complete and proven by lints and unit tests without a running stack, so that every later phase of the agents restructuring builds on a verified static layer.

## Scope

- Phase 1 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 1 of its iteration plan plus the stack-free part of its phase 4. The design, the lint catalog and the iteration plan of 089 apply to every criterion below.
- Builds on: the `agents/` tree, the lints under `tests/lint/agents/`, the routine graphs under `agents/routines/`, the tool nodes under `agents/routines/tools/` with their unit tests, and `utils/orchestrator/cron.py`.
- Gate: `pytest tests/lint/agents`, `pytest tests/unit/python/agents` and `pytest tests/unit/python/utils/orchestrator` are green without a running stack, as the Local verification section of 089 runs them.
- Depends on: no other phase.

## Acceptance Criteria

### Layout

- [ ] Every role's `SOUL.md` opens with an `## Objective` section of one sentence, and a lint fails otherwise.
- [ ] A lint fails when a routine calls a skill or a skill calls a role.
- [ ] The translation routine runs translation through `cli/build/i18n` and contains no copy of its logic.

### Routines

- [ ] `python -m agents.routines run <routine>` executes a routine end to end with a stub model node in a unit test.
- [ ] Every shared deterministic tool node exists and has a unit test on a recorded log fixture.
- [ ] A routine node that is not designated as a model node never calls the gateway (unit test).
- [ ] For each failure class of the maintainer routine, a fixture log routes the routine to the listed branch.
- [ ] The CI evidence node finds the change line in a job log, and follows the next run when the first was cancelled by a later merge.
- [ ] A gate during which a long job ran or the tree under test changed is reported as discarded, not as red or green (fixture).
- [ ] Every routine iteration records its evidence source; an iteration without new evidence while the source is still running waits through `make ci-wait`, and the loop ends only after the source completed with nothing new (fixture: a queued run that delivers new failures in later batches).
- [ ] The hang watchdog fires on 15 minutes of silence and does not fire on a long build that keeps writing output.
- [ ] A failure classified as deterministic is not retried, and a flaky one is retried once.
- [ ] A negative control run through `make test-ref` against an older ref imports the module from that ref's worktree, and the printed `__file__` proves it.
- [ ] A job that ends with exit `124` is classified as a budget kill, and the report names the most expensive task classes compared with earlier runs.
- [ ] A run cancelled by a superseding run is not reported as a failure.
- [ ] The maintainer routine sets labels before the push, and posts review replies only after the push and after the next automated review was read.
- [ ] A branch with a prefix outside the allowed list is refused before the first push (unit test), and a local lint applies the same list.
- [ ] Check runs a new pull request inherits through the same commit SHA from an older pull request are reported as stale, not as failures.
- [ ] A seeded rate-limit failure is classified as external but structural, and the report states whether the pull went through the mirror or the cache.
- [ ] Adding a new environment key runs the affected suites with `true` and with `false`, and a test that does not clear the key fails one of the two runs (fixture).
- [ ] Triage step zero marks the findings of a run whose head SHA is not the branch head as stale (fixture).
- [ ] Every agent pull request text states the matrix size predicted by `scripts/meta/resolve/diff/affected_roles.sh` before its first push.
- [ ] A red job without a citable log line is reported as unattributed, and the re-run request goes to the operator as an `ask` (fixture with a `404` log).
- [ ] Two consecutive triage rounds with the same red job ids, heads and comments make the routine wait through `make ci-wait` instead of starting a third round (fixture).
- [ ] An open pull request whose current head has no unfinished `pull_request` run, after a cancelled run whose job never got a runner, is reported as "CI not active" with the `gh run rerun` command for the operator (fixture).
- [ ] `agents/skills/` holds the rule that environment differences are declared capabilities, never runtime-identity checks, and a lint flags new `runs_on_github` or `RUNTIME` branches in role logic.

### Forges and external accounts

- [ ] Every push command of a routine names its remote and ref (lint test).

### Account naming

- [ ] Agent account names match `<role code>0<suffix>` within `IAM_ACCOUNT_MAX_LENGTH`, and instance ids match `[a-z1-9]{1,15}` (lint).

### Lint tests

- [ ] Every lint of the catalog (L01 to L34) exists under `tests/lint/agents/` and runs in `make test-lint`.
- [ ] `agents/criteria.yml` names a catalog lint id for every lint-proven criterion, and a criterion pointing to a missing lint id fails L22.

### End to end

- [ ] `python -m cli.tune.logscan` reports per-task cost, per-item loops by their count and retry waits from a fixture deploy log.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
