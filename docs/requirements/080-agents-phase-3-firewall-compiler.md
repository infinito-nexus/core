# 080 - Agents Phase 3: Firewall Compiler

## User Story

As an operator, I want the agent firewall compiler to turn the `allow`, `ask` and `deny` rules of `agents/firewall/` into proven decisions and generated settings, so that every surface the control plane deploys later receives limits that unit tests have already checked.

## Scope

- Phase 3 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 2 of its iteration plan. The Agent firewall and Safety controls sections of 089 define the rules and grants.
- Builds on: `agents/firewall/` (roles, variables, providers), `utils/firewall/parse.py`, `utils/firewall/compile.py` and the lints L08 to L12.
- Gate: the compiler unit tests and the firewall lints are green; the generated managed settings are probed in a single `web-app-workspace` deploy.
- Depends on: [078](078-agents-phase-1-foundations.md).

## Acceptance Criteria

### Routines

- [x] An `ask` hit outside a declared gate node is reported as a firewall misconfiguration.
  - Evidence: `at_step` in `utils/firewall/compile.py`, proven by `test_an_ask_at_a_gate_node_is_asked`, `test_an_ask_outside_a_gate_node_is_a_misconfiguration` and `test_allow_and_deny_pass_unchanged` in `tests/unit/python/utils/firewall/test_compile.py`.

### Forges and external accounts

- [x] An external provider declared in `agents/firewall/providers/` is usable in an `account` grant, and a grant naming an undeclared provider fails the lint.
  - Evidence: `test_a_declared_provider_is_usable_in_an_account_grant` in `tests/lint/agents/test_l08_firewall_parses.py` (a declared `codeberg` provider resolves through `decide` to `allow`, an undeclared `bitbucket` grant fails `check`).

### Agent firewall

- [x] A unit test proves `deny` beats `ask` beats `allow` and that an unmatched request is denied.
  - Evidence: `test_deny_beats_ask_beats_allow` and `test_an_unmatched_request_is_denied` in `tests/unit/python/utils/firewall/test_compile.py` over `decide` (`utils/firewall/compile.py`).
- [x] A rule target with `${VAR}` expands from the deploy variables, and the `make i18n-translate` lane address is granted that way.
  - Evidence: `substitute` in `utils/firewall/parse.py` and `expand` in `utils/firewall/compile.py`; the translator grant `egress(${INFINITO_BIND_IP}:${INFINITO_TOOLS_LIBRETRANSLATE_PORT})` in `agents/firewall/roles.yml` with both names in `agents/firewall/variables.yml`; proven by `test_the_translation_lane_address_is_granted_by_its_variables`, `test_a_variable_the_deploy_lacks_is_refused` and `test_a_rule_without_variables_is_kept` in `tests/unit/python/utils/firewall/test_compile.py`.
- [ ] The workspace's `/etc/claude-code/managed-settings.json` is generated from the agent's grants, owned by root, read-only, and the agent process runs as a non-root user that cannot change it (probe recorded).
  - Live: deploy `web-app-workspace` once, then probe inside the container that the file is `root:root` mode `0444`, equals the `managed_settings` surface the compiler emits for the agent's grants, and that a write as the agent user fails.
- [x] `agents/firewall/` ships every baseline role of the design table with the grants listed there.
  - Evidence: `TestBaselineRoles` in `tests/unit/python/utils/firewall/test_compile.py` (`test_every_baseline_role_grants_its_table_row`, `test_the_table_covers_every_baseline_role`) resolves every role of `agents/firewall/roles.yml` against the design table rows.
- [x] The root `AGENTS.md` permission rules for interactive sessions are expressed by the `interactive` firewall role, derived from `.claude/settings.json`.
  - Decision (operator pick, 2026-11-12 ~18:55): `.claude/settings.json` stays the permission SPOT the root `AGENTS.md` names, so the compiler derives the `interactive` role from that file and generates nothing.
  - Evidence:
    - `interactive` in `agents/firewall/roles.yml` keeps its includes and its cross-session channel grant, which no Claude Code permission expresses, and takes its command verdicts through `settings: .claude/settings.json`.
    - `_settings_rules` and `resolve` in `utils/firewall/compile.py` turn every entry of the file's `allow`, `ask` and `deny` lists into a `tool` rule, kept verbatim.
    - `managed_settings` emits only those `tool` rules.
    - Tests in `tests/unit/python/utils/firewall/test_compile.py`:
      - `test_the_interactive_role_carries_exactly_the_permission_lists_of_the_file` compares the compiled lists with the file. Run against the base `roles.yml`, it fails.
      - `TestInteractiveSettings` covers the verbatim match, the write gate and variable expansion.
      - The `interactive` rows of `TestBaselineRoles` check the design row's cross-session messages, its commit, comment and close asks and its push deny.

### Security controls

- [x] A node that reads untrusted content runs without an agent runtime and without tools, and only its schema output reaches tool-using nodes (unit test).
  - Evidence: model nodes carry no callable (`test_no_model_node_carries_a_callable` in `tests/unit/python/agents/routines/test_model_nodes.py`); `build` in `agents/routines/contract.py` wraps every model node in `screened`, which runs it on a copy of the state and passes on only the keys of its `output_schema` and a branch label, refusing a schema value of another type (`TestModelOutputSchema` and `test_the_model_node_is_screened` in `tests/unit/python/agents/routines/test_contract.py`).
- [x] With `write_enabled: false`, or with a failed deny, kill-switch, audit or identity scenario, the compiler emits no write grant for the agent.
  - Evidence: `write_gate` in `utils/firewall/compile.py`, proven by `test_write_disabled_emits_no_write_grant`, `test_a_failed_gate_scenario_emits_no_write_grant`, `test_a_missing_scenario_result_emits_no_write_grant` and `test_write_enabled_with_every_scenario_passed_keeps_the_grants` in `tests/unit/python/utils/firewall/test_compile.py`.
- [x] The lint flags an `app` grant that maps to a privileged group.
  - Evidence: `check` in `tests/lint/agents/test_l10_privileged_grants.py`, proven by `test_real_tree_passes` and `test_red_fixture_fails`.

### Profile catalog

- [x] A started agent's effective rights equal the intersection of the profile's grants and its owner's rights (unit test over the compiler).
  - Evidence: `decide_intersection` in `utils/firewall/compile.py`, proven by `test_a_right_both_hold_is_granted`, `test_a_right_the_owner_lacks_is_denied`, `test_a_right_the_profile_lacks_is_denied` and `test_the_stricter_verdict_wins` in `tests/unit/python/utils/firewall/test_compile.py`.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
