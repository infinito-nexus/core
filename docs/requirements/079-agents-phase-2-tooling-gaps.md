# 079 - Agents Phase 2: Tooling Gaps

## User Story

As an operator, I want every make target the routine tool nodes need to exist and every defect the running agents reported in existing targets to be fixed, so that the routines of the agents restructuring call deterministic tooling instead of working around it.

## Scope

- Phase 2 of [089 - Agents and AI Restructuring](089-agents-restructuring.md). The Tooling gaps section of 089 lists the targets and defects the criteria below refer to.
- Builds on: the make targets that already exist (`ci-wait`, `test-ref`, `i18n-load`, `i18n-pause`, `i18n-resume`, `legal-inventory`, `legal-probe`, `design-gallery`) and the routine tool nodes of [078](078-agents-phase-1-foundations.md).
- Gate: every criterion is proven by its own run of the target on a local development stack, recorded in `agents/criteria.yml`.
- Depends on: no other phase; it MAY be implemented in parallel to phase 1.

## Acceptance Criteria

### Tooling gaps

- [ ] Each make target listed under Tooling gaps exists, is documented in `make help` and is called by the routine that needs it.
- [x] The lint for one role or one file reports a key-order error in `default.env` and a prefix-group error in a handler file name within one minute, without the full gate.
  - Evidence: `make lint-file file=<path>` and `make lint-role role=<role>` run the lint modules that call `in_lint_scope` (`utils/cache/files.py`) through `scripts/tests/code/run.sh` with `lint_scope` and `test_paths`; the scoped selection run directly with `lint_scope="default.env roles/web-app-keycloak/handlers/restart_db.yml"` reported `default.env` out of order and the seeded `restart_*` handler group in 1.6 s.
- [x] The affected-roles resolver keeps a pull request that only adds a test under `tests/` at its real matrix instead of `__ALL__`.
  - Evidence: a path under `tests/` seeds the role of its first `roles/<role>/` segment in `scripts/meta/resolve/diff/affected_roles.sh` and in `seeded_role` of `cli/meta/ci/iterate/plan.py`, proven by `test_only_a_role_test_seeds_its_role` in `tests/integration/meta/workflows/test_diff_affected_roles.py` and `test_a_role_test_seeds_the_baseline_like_the_script` in `tests/unit/python/cli/meta/ci/iterate/test_plan.py`.
- [ ] `make compose-role-sync task=<task> pw=<args>` runs the spec.
- [ ] `make compose-playwright` runs the current spec and `.env`.
- [ ] `make design-palette sync=role` re-renders `.env`.
- [ ] `make compose-deploy mode=update` finds the inventory written by `make roundtrip` without an explicit `variant`.
- [ ] Gallery screenshots land in the run directory, not in the host `/tmp`.
- [x] The install stamp stays valid after a commit hook run.
  - Evidence: `scripts/install/all.sh` records the SHA-256 of its inputs in the stamp instead of comparing mtimes, proven by `test_unchanged_rewrite_keeps_the_stamp` in `tests/unit/python/scripts/install/test_all.py`, which rewrites every input unchanged with a later mtime.
- [ ] `make quality-high` installs every lint tool before the parallel lint dispatch, and ten parallel runs show no import race.
- [x] The quality gate reports a lint failure in a new untracked file.
  - Evidence: `repository_files` in `utils/cache/files.py` lists the untracked files `.gitignore` does not exclude by default, proven by `test_default_adds_the_files_gitignore_does_not_exclude` in `tests/unit/python/utils/cache/test_files.py`; two untracked handler files were reported by `tests/lint/repository/structure/test_prefix_grouped_files.py`.
- [ ] npm installs succeed inside the sandbox.
- [x] The slot picker refuses a slot whose subnet a leftover network still holds.
  - Evidence: `worktree_taken_slots` in `scripts/system/worktree/lib.sh` lists every slot whose compose or swarm lab subnet a docker network holds and `worktree_allocate_slot` hands them to the slot registry in `cli/administration/deploy/development/slots.py`, which skips them, proven by `TestWorktreeTakenSlots` and `TestWorktreeSlotRegistryCalls` in `tests/unit/python/scripts/system/worktree/test_lib.py` with a stub `docker` on `PATH`, and by `test_the_lowest_slot_no_entry_and_no_network_holds_is_allocated` in `tests/unit/python/cli/administration/deploy/development/test_stack_name.py`.
- [x] `agents/skills/` holds a rule for writing escapes in code (`\U0000XXXX` or `\N{NAME}`, never `\uXXXX` through the Edit or Write tool), and a lint flags private-use or surrogate characters in source files.
  - Evidence: the rule in `agents/skills/i8-develop/SKILL.md`; L19 scans every source file of the project (`pua_problems` over `source_files` in `tests/lint/agents/test_l19_no_private_use_chars.py`), proven by `test_every_source_file_passes` and `test_red_fixture_fails` (a private-use and a surrogate case).
- [x] A routine fetch succeeds when a fork tag is clobbered.
  - Evidence: `fetch_argv` in `agents/routines/tools/fetch.py` fetches with `--no-tags`, and the `trigger` step of `agents/routines/push_trigger_pull.py` runs it, proven by `TestClobberedTagFetch` in `tests/unit/python/agents/routines/tools/test_fetch.py` with an upstream and a fork repository whose tag moved.

### Lint tests

- [ ] Every lint of the catalog runs alone through the lint target for one role or one file.
  - Partial: `make lint-file file=<path> test=<lint module>` runs one module alone through `scripts/tests/code/run.sh`. Open: the catalog lints `tests/lint/agents/test_l01` to `test_l34` do not read `in_lint_scope` yet, so they run unscoped.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
