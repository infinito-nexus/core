# 127 - Platform Deploy Fixture

## User Story

As a maintainer of the workspace roles, I want the Semaphore deploy fixture to include the platform host, so that the live workspace specs run against a real platform while no credential is committed to the fixture repository and no production host gains root access for a runner.

## Background

The operator picked this on 2026-11-14 during the IAM store round (variant B), after the fixture lane found four gaps.

### Today

- One provision call for `SEMAPHORE_DEPLOY_FIXTURE_HOST` (`target`) builds the fixture repository in `roles/web-app-semaphore/tasks/utils/project/fixture/commit.yml`. `tests/unit/python/roles/web-app-semaphore/test_fixture_commit.py` refuses any credential the fixture commits.
- The runner reaches the platform host only as the app-control user, through a forced-command key (`roles/sys-svc-app-control/vars/main.yml`). `INFINITO_TARGET_KEY` gives root only on the shared target (`compose/target/README.md`).
- `deploy.sh` runs `devices.yml` without `--limit`, and `workspace.sh` reads the same file through `WORKSPACE_INVENTORY_FILE`, so a platform host in it would also receive every foreign `deploy`.
- `resolve()` in `utils/openbao_client.py` replaces OpenBao references only below `secrets.credentials` ([106](106-infinito-deploy-reads-credentials-from-openbao.md) decision 2), and provision pins `users.*.password` in host_vars, so a fresh fixture carries new passwords the live platform does not know.
- `workspace.sh` calls `ansible-playbook` directly without the 106 pre-flight, and the `members` jwt role is bound only to the `members` template.

## Decisions

1. **Two inventories, one repository.** The fixture repository holds `devices.yml` with the customer devices, the inventory of the `deploy` template, and `workspaces.yml` with the platform hosts, the inventory of the Workspaces project. `WORKSPACE_INVENTORY_FILE` names `workspaces.yml`, so a `deploy` run never reaches a platform host, and the one-repository rule of [102](102-one-semaphore-runner-per-workspace.md) holds.
2. **User passwords as OpenBao references.** `users.<name>.password` MAY hold an OpenBao reference `{openbao: "<mount>/<path>#<field>"}`, resolved exactly like a `secrets.credentials` leaf. This extends 106 decision 2 to this one leaf; every other `users` field holding a reference is refused.
3. **Fixture credentials live in OpenBao.** The deploy that builds the fixture writes the credentials of the platform host that the workspace roles need below `platform/data/fixture/<host>/`: user passwords at `fixture/<host>/users/<name>`, field `password`, and application credentials at `fixture/<host>/apps/<application_id>`, one field per credential. The fixture's host_vars hold only references to them.
4. **A read-only fixture reader.** Policy `fixture` reads `platform/data/fixture/*` and nothing else. Jwt role `workspace-fixture` binds it to the Workspaces project id and the `workspace` template id. `workspace.sh` logs in with it before `ansible-playbook` (the 106 pre-flight) and fails closed without a login.
5. **Root SSH only in test runtimes.** A dedicated fixture key gives the runner root on the platform host only while `SEMAPHORE_DEPLOY_FIXTURE_ENABLED` is true. A production inventory never renders that key, and the key differs from the app-control key and the target key.

## Acceptance Criteria

### Inventory

- [x] The fixture repository commits `devices.yml` without any platform host and `workspaces.yml` with the platform host; the `deploy` template's inventory is `devices.yml` and the Workspaces project's is `workspaces.yml`. A planted platform host in `devices.yml` fails the test. (`semaphore_fixture_workspaces` and `semaphore_fixture_inventory_findings` in `roles/web-app-semaphore/filter_plugins/semaphore_fixture_platform.py`, asserted in `roles/web-app-semaphore/tasks/utils/project/fixture/commit.yml` before the commit collects its files; proven by `test_devices_and_workspaces_are_two_inventories` and `test_negative_control_a_platform_host_planted_in_devices_is_caught` in `tests/unit/python/roles/web-app-semaphore/test_fixture_commit.py` and by `test_negative_control_a_platform_host_planted_in_devices_fails` in `tests/unit/python/roles/web-app-semaphore/filter_plugins/test_semaphore_fixture_platform.py`.)
- [ ] The foreign deploy spec never reaches the platform host.

### Credentials

- [x] `lookup('users', <name>).password` resolves an OpenBao reference, and a reference in any other `users` field is refused, naming the field. (`resolve_users` in `utils/openbao_client.py`, called by `plugins/lookup/users.py` and the `users.` paths of `plugins/lookup/config.py`, and read by the pre-flight in `cli/administration/deploy/dedicated/openbao.py`; proven by `test_the_users_lookup_resolves_a_password_reference`, `test_the_config_lookup_resolves_a_user_password_reference` and `test_negative_control_a_reference_in_any_other_users_field_is_refused` in `tests/unit/python/plugins/lookup/test_users_openbao.py` against the HTTPS stub, and by `test_negative_control_a_reference_in_another_users_field_is_refused` in `tests/unit/python/roles/web-app-semaphore/files/test_workspace_sh_preflight.py` for the pre-flight.)
- [x] The fixture commit holds no credential value, only references (`test_fixture_commit.py` and its controls). (The platform files reach the commit only through `semaphore_fixture_host_vars`, which drops every credential value, overlays `SEMAPHORE_DEPLOY_FIXTURE_REFERENCES` and refuses a vaulted value or a credential that is no reference; proven by `test_the_platform_files_reach_the_commit_only_through_their_filters` and `test_negative_control_raw_platform_host_vars_are_caught` in `test_fixture_commit.py` and by `test_no_credential_value_and_no_ciphertext_survive` with its three refusal controls in `test_semaphore_fixture_platform.py`.)
- [ ] The fixture deploy writes the platform credentials below `platform/data/fixture/<host>/` and a second run reports no change.

### Reader

- [x] Policy `fixture` grants `read` on `platform/data/fixture/*` and nothing else; a planted wider path fails the test. (`roles/web-app-openbao/templates/policies/fixture.hcl.j2`, written by `roles/web-app-openbao/tasks/07_workspaces.yml`; proven by `test_the_fixture_policy_reads_the_fixture_folder_only` and `test_negative_control_a_planted_wider_path_fails` in `tests/unit/python/roles/web-app-openbao/test_fixture_reader.py`.)
- [x] Jwt role `workspace-fixture` is bound to the Workspaces project id and the `workspace` template id; a JWT of another template is refused. (`roles/web-app-openbao/templates/fixture_reader_role.json.j2` over `semaphore_fixture_reader_identity`, which `roles/web-app-semaphore/tasks/utils/workspaces/identity.yml` sets only while the fixture is on; proven by `test_the_reader_role_binds_the_workspace_template` and `test_negative_control_a_jwt_of_another_template_is_refused` in `tests/unit/python/roles/web-app-openbao/test_fixture_reader.py` against a model of OpenBao's bound-claims match, and by `test_negative_control_a_jwt_of_another_template_is_refused` in `tests/unit/python/roles/web-app-semaphore/files/test_workspace_sh_preflight.py`, where a refused login stops `workspace.sh` before the play.)
- [x] `workspace.sh` logs in before `ansible-playbook` and stops before it without a login. (`roles/web-app-semaphore/files/python/bao/preflight.py` runs the 106 pre-flight and only then the play; proven by `test_workspace_sh_logs_in_before_the_playbook`, `test_without_a_login_workspace_sh_stops_before_the_playbook` and `test_a_denied_reference_stops_before_the_playbook` in `tests/unit/python/roles/web-app-semaphore/files/test_workspace_sh_preflight.py`.)

### SSH

- [x] The fixture key is authorized for root on the platform host only while `SEMAPHORE_DEPLOY_FIXTURE_ENABLED` is true; a production render carries no such key. A planted key under a production render fails the test. (`roles/web-app-semaphore/tasks/utils/project/fixture/root.yml` writes the key file and the `Match User root` drop-in only under the gate and removes both otherwise; proven by `test_only_test_runtimes_turn_the_fixture_key_on`, `test_negative_control_a_key_planted_under_a_production_render_fails`, `test_every_write_of_the_root_key_is_gated_by_the_fixture` and `test_negative_control_an_ungated_key_write_is_caught` in `tests/unit/python/roles/web-app-semaphore/test_fixture_root.py`, and by `test_the_fixture_key_reaches_the_workspaces_project_alone` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`.)
- [x] The fixture key differs from the app-control key and the target key. (Credential `fixture_ssh_key` of its own, and a runtime assert in `root.yml` through `semaphore_fixture_key_findings` against the app-control, deploy and target keys; proven by `test_the_fixture_key_is_a_generated_key_of_its_own` and `test_negative_control_a_fixture_key_equal_to_app_control_or_target_is_caught` in `test_fixture_root.py` and by `test_negative_control_a_key_equal_to_app_control_deploy_or_target_is_caught` in `test_semaphore_fixture_platform.py`.)

### Specs

- [ ] The workspace variant that asked for B turns the platform fixture on, and the workspace specs that skipped for a missing platform host run against it.

### Documentation

- [x] The [README](../../roles/web-app-semaphore/README.md) documents the two inventories, the fixture credentials in OpenBao, the reader role and the test-only root key. (Items **Fixture inventories**, **Fixture credentials**, **Fixture reader** and **Fixture root key** of its deploy section.)
