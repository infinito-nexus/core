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

- [x] Every role's `SOUL.md` opens with an `## Objective` section of one sentence, and a lint fails otherwise.
  - Evidence: `objective_problems` in `tests/lint/agents/test_l02_role_files.py`, proven by `test_real_tree_passes` and the red cases `test_objective_after_another_section_fails`, `test_two_sentence_objective_fails`, `test_objective_without_a_sentence_end_fails` (lines 60-86).
- [x] A lint fails when a routine calls a skill or a skill calls a role.
  - Evidence: `check` and `check_skills` in `tests/lint/agents/test_l04_routine_layering.py`, proven by `test_real_skills_pass`, `test_skill_calling_a_role_fails`, `test_skill_frontmatter_naming_roles_fails` and `test_red_fixture_fails`.
- [x] The translation routine runs translation through `cli/build/i18n` and contains no copy of its logic.
  - Evidence: `tests/unit/python/agents/routines/test_translate.py` (`test_the_steps_name_the_i18n_targets`, `test_every_named_target_runs_cli_build_i18n`, `test_the_routine_holds_no_copy_of_the_logic`, red cases `test_a_copied_function_is_found`, `test_a_target_outside_cli_build_i18n_is_found`).

### Routines

- [ ] `python -m agents.routines run <routine>` executes a routine end to end with a stub model node in a unit test.
  - Open: `test_stub_run_reaches_a_terminal` (`tests/unit/python/agents/routines/test_maintainer.py`) skips, since `langgraph` is declared neither in `pyproject.toml` nor in `roles/svc-ai-agent-orchestrator/files/Dockerfile`.
- [x] Every shared deterministic tool node exists and has a unit test on a recorded log fixture.
  - Evidence: `untested` in `tests/unit/python/agents/routines/tools/test_coverage.py`, proven by `test_every_tool_has_a_test` (24 tool modules, 24 test modules) and the red case `test_a_tool_without_a_test_is_named`.
- [x] A routine node that is not designated as a model node never calls the gateway (unit test).
  - Evidence: `tests/unit/python/agents/routines/test_model_nodes.py` (`test_no_model_node_carries_a_callable`, `test_every_callable_step_runs_without_the_network` over every callable step with `socket` cut off, red case `test_a_node_that_calls_out_is_caught`).
- [ ] For each failure class of the maintainer routine, a fixture log routes the routine to the listed branch.
  - Partial: the decision node `C1` (`failure_class` in `agents/routines/maintainer.py`, named in the 089 maintainer diagram) routes starved queue cancellation, superseded run, unattributed, budget kill and external but structural to their branches, proven by `TestFailureClassRouter` in `tests/unit/python/agents/routines/test_maintainer.py` (one fixture log per class, red cases for a citable line beside a `404` and a red gate with exit `124`). Open: the other eight classes have no deterministic log signal yet and are still chosen by the model node `L2`.
- [x] The CI evidence node finds the change line in a job log, and follows the next run when the first was cancelled by a later merge.
  - Evidence: `evidence_run` in `agents/routines/tools/ci_state.py` with `change_ran` from `agents/routines/tools/log_scan.py`, proven by `test_the_evidence_follows_the_run_after_a_cancelled_one` and `test_no_run_with_the_fix_is_no_evidence` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [x] A gate during which a long job ran or the tree under test changed is reported as discarded, not as red or green (fixture).
  - Evidence: `gate_discarded` in `utils/orchestrator/cron.py`, proven by `test_long_job_beside_the_gate_discards`, `test_tree_change_discards` and the clean case in `tests/unit/python/utils/orchestrator/test_cron.py`.
- [x] Every routine iteration records its evidence source; an iteration without new evidence while the source is still running waits through `make ci-wait`, and the loop ends only after the source completed with nothing new (fixture: a queued run that delivers new failures in later batches).
  - Evidence: `iteration_action` in `agents/routines/tools/ci_state.py` with the queued-run fixture `test_a_queued_run_is_followed_until_it_completed_with_nothing_new` (`tests/unit/python/agents/routines/tools/test_ci_state.py`); every iterate decision records through `decide` (`agents/routines/contract.py`), whose ledger record carries the state's `evidence_source`, which `python -m agents.routines decide` sets from its `--log`, `--junit`, `--exit-file` and `--pid` (`test_decide_records_the_evidence_source_the_state_names` in `tests/unit/python/agents/routines/test_contract.py`, `test_the_ledger_names_the_evidence_source` in `tests/unit/python/agents/routines/test_main.py`).
- [ ] The hang watchdog fires on 15 minutes of silence and does not fire on a long build that keeps writing output.
  - Decision (operator pick, 2026-11-12 ~18:55): every long step logs a heartbeat, liveness also counts the stack's cgroup CPU, and one `SILENCE_SECONDS` of 900 s covers every role and slot, with no per-task budget.
  - Partial: the following are proven, each with a negative control.
    - `SILENCE_SECONDS` and `stack_busy` in `agents/routines/tools/watchdog.py` (read by `_hung` in `agents/routines/iterate/__init__.py`) are proven by these tests in `tests/unit/python/agents/routines/tools/test_watchdog.py`: `test_the_threshold_is_fifteen_minutes`, `test_a_silent_run_fires_after_fifteen_minutes`, `test_a_heartbeat_run_does_not_fire` and `test_a_long_build_that_keeps_writing_does_not_fire`. `TestBusyStack` in `tests/unit/python/agents/routines/iterate/test_decisions.py` proves the busy-stack cases.
    - In the Playwright role, the onion probe loops log a retry line at most every 135 s and the serial pass polls every 10 s. `TestHeartbeat` in `tests/unit/python/roles/test-e2e-playwright/test_parallel_orchestration.py` pins both to `SILENCE_SECONDS`.
  - Open: live proof in the final roundtrip. It needs an onion deploy whose probe and pass outlast 15 minutes without a false hang.
- [x] A failure classified as deterministic is not retried, and a flaky one is retried once.
  - Evidence: `should_retry` in `agents/routines/tools/retry.py`, proven by `test_flaky_is_retried`, `test_flaky_is_retried_only_once` and `test_deterministic_is_not_retried` in `tests/unit/python/agents/routines/tools/test_retry.py`.
- [ ] A negative control run through `make test-ref` against an older ref imports the module from that ref's worktree, and the printed `__file__` proves it.
  - Live: run `make test-ref ref=<older ref> test=<a test that prints its module __file__>` and confirm the printed path with `imported_from_ref` (`agents/routines/tools/ref_probe.py`).
- [x] A job that ends with exit `124` is classified as a budget kill, and the report names the most expensive task classes compared with earlier runs.
  - Evidence: `agents/routines/tools/budget.py`, proven by `test_timeout_with_green_tests_is_a_kill`, `test_non_timeout_exit_is_not_a_kill` and `test_expensive_classes_ranked_by_growth` in `tests/unit/python/agents/routines/tools/test_budget.py`.
- [x] A run cancelled by a superseding run is not reported as a failure.
  - Evidence: `agents/routines/tools/superseded.py`, proven by `test_superseded_run_recognised` and `test_genuine_failure_not_superseded` in `tests/unit/python/agents/routines/tools/test_superseded.py`.
- [x] The maintainer routine sets labels before the push, and posts review replies only after the push and after the next automated review was read.
  - Evidence: the label step `D17` before the push `D8` and the decision `D18` (`_review_read`: the review's SHA equals the pushed head, else `D19` waits through `make ci-wait`) before `L6` and the reply `D12` in `agents/routines/maintainer.py` and the 089 maintainer diagram, proven by `TestMaintainerOrder` (no path reaches `D8` without `D17`, nor `D12` without `D8` and `D18`) and `test_a_review_of_an_older_head_is_not_yet_read` in `tests/unit/python/agents/routines/test_maintainer.py`, and by `test_graph_diagrams.py`.
- [x] A branch with a prefix outside the allowed list is refused before the first push (unit test), and a local lint applies the same list.
  - Evidence: `prefix_ok` in `agents/routines/tools/branch_prefix.py` and the `prefix` decision before `push` in `agents/routines/push_trigger_pull.py`, proven by `test_unknown_prefix_refused`, `test_the_local_lint_applies_the_same_list` (equal to `VALID_PREFIXES` and `BRANCH_RE` of `tests/lint/repository/naming/test_branch_name.py`) and `test_the_routine_refuses_before_the_push` in `tests/unit/python/agents/routines/tools/test_branch_prefix.py`.
- [x] Check runs a new pull request inherits through the same commit SHA from an older pull request are reported as stale, not as failures.
  - Evidence: `inherited_stale` in `agents/routines/tools/ci_state.py`, proven by `test_inherited_checks_stale_on_same_sha` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [x] A seeded rate-limit failure is classified as external but structural, and the report states whether the pull went through the mirror or the cache.
  - Evidence: `classify` and `report` in `agents/routines/tools/rate_limit.py`, proven by `test_a_seeded_rate_limit_is_external_but_structural`, `test_the_report_states_the_pull_path` and `test_the_report_names_a_pull_outside_mirror_and_cache` in `tests/unit/python/agents/routines/tools/test_rate_limit.py`.
- [x] Adding a new environment key runs the affected suites with `true` and with `false`, and a test that does not clear the key fails one of the two runs (fixture).
  - Evidence: `run_both` and `leaks` in `agents/routines/tools/env_key.py`, proven by `test_two_runs_true_then_false`, `test_a_test_that_does_not_clear_the_key_fails_one_run` and `test_a_test_that_clears_the_key_passes_both_runs` in `tests/unit/python/agents/routines/tools/test_env_key.py`.
- [x] Triage step zero marks the findings of a run whose head SHA is not the branch head as stale (fixture).
  - Evidence: `triage_stale` in `agents/routines/tools/ci_state.py`, proven by `test_triage_stale_on_head_mismatch` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [ ] Every agent pull request text states the matrix size predicted by `scripts/meta/resolve/diff/affected_roles.sh` before its first push.
  - Partial: the `predict` step before `push` in `agents/routines/push_trigger_pull.py`, `D16` before the push `D8` in `agents/routines/maintainer.py` and `D9` before the push `D7` in `agents/routines/implementer.py` (089 diagrams updated), with `matrix_line`/`states_matrix` in `agents/routines/tools/affected.py`, proven by `TestMatrixLine` in `tests/unit/python/agents/routines/tools/test_affected.py`, `test_the_matrix_is_predicted_before_the_push` in `test_maintainer.py` and `test_implementer.py`. Open: the designer (`agents/routines/design.py`, push in `D9`) and translator routines open pull requests without that step.
- [x] A red job without a citable log line is reported as unattributed, and the re-run request goes to the operator as an `ask` (fixture with a `404` log).
  - Evidence: `attribution` in `agents/routines/tools/ci_state.py`, proven by `test_unattributed_job_asks_the_operator_for_the_rerun` and `test_attributed_job_cites_its_line_and_asks_nothing` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [x] Two consecutive triage rounds with the same red job ids, heads and comments make the routine wait through `make ci-wait` instead of starting a third round (fixture).
  - Evidence: `next_round` in `agents/routines/tools/ci_state.py`, proven by `test_two_identical_rounds_wait_instead_of_a_third` and `test_a_new_head_starts_another_round` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [x] An open pull request whose current head has no unfinished `pull_request` run, after a cancelled run whose job never got a runner, is reported as "CI not active" with the `gh run rerun` command for the operator (fixture).
  - Evidence: `starved` and `liveness` in `agents/routines/tools/ci_state.py`, proven by `test_a_job_without_steps_or_runner_is_starved`, `test_a_head_left_cancelled_by_a_starved_job_is_not_active` and `test_a_head_with_a_live_run_reports_nothing` in `tests/unit/python/agents/routines/tools/test_ci_state.py`.
- [x] `agents/skills/` holds the rule that environment differences are declared capabilities, never runtime-identity checks, and a lint flags new `runs_on_github` or `RUNTIME` branches in role logic.
  - Evidence: the rule in `agents/skills/i8-debug-ci/SKILL.md`; L18 scans role logic (`roles/`, `plugins/`, `group_vars/`) besides `agents/`, proven by `test_role_logic_passes` and `test_red_fixture_fails` in `tests/lint/agents/test_l18_declared_capabilities.py`.

### Forges and external accounts

- [x] Every push command of a routine names its remote and ref (lint test).
  - Evidence: `label_problems` in `tests/lint/agents/test_l15_routine_push.py`, proven by `test_real_tree_passes`, `test_a_push_naming_remote_and_ref_passes` and `test_red_fixture_fails` (no remote, no ref).

### Account naming

- [x] Agent account names match `<role code>0<suffix>` within `IAM_ACCOUNT_MAX_LENGTH`, and instance ids match `[a-z1-9]{1,15}` (lint).
  - Evidence: `tests/lint/agents/test_l06_account_names.py` (`test_every_role_code_fits_the_longest_agent_name`, `test_instance_ids_follow_the_rule`, `test_the_generator_ceilings_equal_the_account_policy`, `test_red_fixture_fails`) over `is_instance_id` in `utils/agents/naming.py`.

### Lint tests

- [x] Every lint of the catalog (L01 to L34) exists under `tests/lint/agents/` and runs in `make test-lint`.
  - Evidence: `tests/lint/agents/test_l01_agent_fields.py` to `test_l34_tuner_rules.py`, one file per id; `make test-lint` discovers `tests/lint` recursively (`scripts/tests/code/run.sh`); `catalog` in `tests/lint/agents/test_l22_criteria_map.py` reads the ids from those file names.
- [x] `agents/criteria.yml` names a catalog lint id for every lint-proven criterion, and a criterion pointing to a missing lint id fails L22.
  - Evidence: `lint_id_problems` in `tests/lint/agents/test_l22_criteria_map.py`, proven by `test_real_tree_passes` and `test_a_criterion_naming_a_missing_lint_id_fails`.

### End to end

- [x] `python -m cli.tune.logscan` reports per-task cost, per-item loops by their count and retry waits from a fixture deploy log.
  - Evidence: `cli/tune/logscan.py` (`RETRYING` keyed per task), proven by `test_reports_the_cost_per_task_slowest_first`, `test_reports_a_per_item_loop_by_its_count`, `test_reports_the_retry_waits_per_task` and `test_retries_are_counted_per_task_not_per_host` in `tests/unit/python/cli/tune/test_logscan.py`.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
