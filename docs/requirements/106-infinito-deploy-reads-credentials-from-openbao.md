# 106 - infinito deploy Reads Credentials from OpenBao

## User Story

As the operator of a platform whose workspace inventories live in git, I want an inventory credential to be a reference to an OpenBao path that `infinito deploy` resolves with the task's own OpenBao login, so that a workspace inventory holds no `!vault` block, a deploy needs no vault password, and a missing or denied secret stops the deploy with the path it could not read.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 9, criteria 062:82 and 062:128) needs this core side.

### Today

- `infinito administration deploy dedicated` takes an optional vault password file (`cli/administration/deploy/dedicated/command.py:116-118`) and hands it to `ansible-playbook` as `--vault-password-file` (`cli/administration/deploy/dedicated/runner.py:167-168`).
- Generated credentials are written into the inventory as vault blocks (`to_vault_block` in `cli/administration/inventory/credentials/vault.py:51-64`) under `secrets.credentials` of each application (`credentials_map` in `cli/administration/inventory/credentials/emit.py:26-33`).
- Every role reads a credential through `lookup('config', <application>, 'secrets.credentials.<key>')`, for example `roles/web-app-semaphore/vars/main.yml:34,108`. The lookup fetches and renders the value in one place (`plugins/lookup/config.py:105-119`).
- Semaphore's `deploy.sh` requires `DEPLOY_VAULT_PASSWORD` and an SSH agent from the inventory key Semaphore holds (`roles/web-app-semaphore/files/shell/repository/deploy.sh:18-21`) and writes the password to a `0400` file in a temporary directory it removes on exit (`deploy.sh:29-34`).
- No OpenBao client exists in core: `cli/`, `plugins/`, `utils/`, `requirements/` and `pyproject.toml` name neither `openbao`, `hashi_vault` nor `hvac`. `community.hashi_vault` is not among the collections (`requirements/requirements.galaxy.yml`).

### Upstream

| Fact | Source |
| --- | --- |
| A JWT login is `POST /v1/auth/jwt/login` with `role` and `jwt`; a KV v2 read is `GET /v1/<mount>/data/<path>`; a create-only write sets `options.cas` to 0. | [OpenBao JWT/OIDC auth API](https://openbao.org/api-docs/auth/jwt/), [OpenBao KV v2 API](https://openbao.org/api-docs/secret/kv/kv-v2/) |
| A Semaphore task receives its token as `SEMAPHORE_JWT`. | `getEnvironmentENV` in [services/tasks/local_executor.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/local_executor.go) |

## Decisions

1. **A typed reference.** A credential leaf under `secrets.credentials` may be a mapping with the single key `openbao`, whose value is `<mount>/<path>#<field>`, for example `openbao: tenant/ws-<id>/ssh#private_key`. Any other value keeps its meaning, vault blocks included. A lint test keeps every role from declaring a credential named `openbao`, so the reference cannot collide with a nested credential.
2. **Resolved in the config lookup.** `plugins/lookup/config.py` resolves a reference where it fetches the value today, so every role reads OpenBao credentials through the same call as before and no role changes. The client is a small module on the standard library's HTTP client. It verifies TLS against the system store or, under `TLS_MODE` `self_signed`, the deployment CA. Rejected: `community.hashi_vault`, which brings `hvac` and a second lookup path beside the one every role uses.
3. **One login per run.** `infinito deploy` logs in once before the play:
   - with `SEMAPHORE_JWT` and the role `BAO_ROLE`, which the locked template sets (103);
   - otherwise with an operator's `BAO_TOKEN`.

   The token reaches the play only in the environment of the controller process and never enters a file or a host. `BAO_ADDR` names the platform's OpenBao.
4. **Fail before any host changes.** Before the first play, the CLI reads every reference of the inventory once and discards the values. A path that is missing (404) or denied (403) stops the deploy with a message that names the path and the field, never the value. A reference that fails later, during the play, fails its task with the same message. Every read uses `no_log` semantics: a value never reaches a log line, a diff or an error message.
5. **No vault password without vault blocks.** A deploy whose inventory holds no `!vault` block runs without `--password-file`. `deploy.sh` requires `DEPLOY_VAULT_PASSWORD` only when the inventory holds a vault block.
6. **SSH key and host keys from OpenBao.** For a workspace deploy, `deploy.sh` loads the SSH key named by the inventory's reference into an agent that lives in its task directory. It writes the pinned host keys into that directory's `known_hosts` (102 decision 5). Nothing comes from Semaphore's key store.
7. **Generated and supplied credentials.** `infinito inventory credentials`, when told to write references, generates each value it generates today into OpenBao with `cas` 0. It never overwrites an existing secret. Then it writes the reference into the inventory. A credential the inventory supplies but does not generate must already exist at its path, or the deploy stops at decision 4.

## Acceptance Criteria

### Reference and resolution

- [ ] A credential given as `{openbao: <mount>/<path>#<field>}` resolves through `lookup('config', ...)` to the field's value. A vault block and a plain value resolve as before (`test_the_config_lookup_resolves_an_openbao_reference` and `test_other_values_keep_their_meaning` in `tests/unit/python/plugins/lookup/test_config_openbao.py`, against an HTTP stub of the OpenBao API).
- [ ] A reference whose value does not match `<mount>/<path>#<field>`, or a mapping with a second key beside `openbao`, is refused with a message that names the credential (`test_a_malformed_reference_is_refused` in `test_config_openbao.py`).
- [ ] No role's `meta/secrets.yml` declares a credential named `openbao` (`test_no_credential_is_named_openbao` in `tests/lint/ansible/test_openbao_reference_name.py`).
- [ ] The client verifies TLS, and under `self_signed` it trusts only the system store plus the deployment CA (`test_the_client_verifies_tls` in `tests/unit/python/utils/test_openbao_client.py`).

### Login

- [ ] With `SEMAPHORE_JWT` and `BAO_ROLE` set, the CLI logs in once per run through `auth/jwt/login` and passes the token to the play only through the controller's environment (`test_the_cli_logs_in_once_with_the_task_token` in `tests/unit/python/cli/administration/deploy/dedicated/test_openbao_login.py`).
- [ ] With `BAO_TOKEN` set and no task token, the CLI uses that token. With neither, an inventory holding a reference stops before the first play with a message naming the missing login (`test_the_cli_falls_back_to_an_operator_token` and `test_a_reference_without_a_login_stops_the_deploy` in `test_openbao_login.py`).

### Failure

- [ ] A missing path and a denied path each stop the deploy before the first play, with a message that names the path and the field. No host is contacted (`test_a_missing_path_stops_before_the_play` and `test_a_denied_path_stops_before_the_play` in `test_openbao_login.py`).
- [ ] No value read from OpenBao appears in the deploy's stdout, stderr, diff output or error messages: a run against the stub with a known value greps clean (`test_no_resolved_value_reaches_the_output` in `test_openbao_login.py`).

### No vault password

- [ ] A deploy of an inventory without a `!vault` block and with references runs to the end without `--password-file`, and `deploy.sh` runs without `DEPLOY_VAULT_PASSWORD` (`workspace deploy: no vault password and no vault block` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`; `test_deploy_sh_needs_a_vault_password_only_for_vault_blocks` in `tests/unit/python/roles/web-app-semaphore/files/test_deploy_sh.py`).
- [ ] A workspace deploy loads its SSH key from OpenBao into an agent whose socket lies in the task directory, and its `known_hosts` from OpenBao. Neither is left once the task ends (`workspace deploy: SSH key and host keys come from OpenBao` in `test-workspace-runners.js`).

### Generated credentials

- [ ] `infinito inventory credentials` in reference mode writes each generated value with `cas` 0 and the reference into the inventory. A second run leaves every existing secret and its version unchanged (`test_generated_credentials_are_written_create_only` in `tests/unit/python/cli/administration/inventory/credentials/test_openbao_references.py`).
- [ ] A supplied credential whose path does not exist stops the deploy at the pre-flight with its path (`test_a_supplied_credential_must_exist` in `test_openbao_references.py`).

### Documentation

- [ ] The deploy and inventory documentation describe the reference form, the login order, the pre-flight and the create-only rule (`test_the_docs_name_the_openbao_reference` in `tests/unit/python/cli/administration/deploy/dedicated/test_docs.py`).
