# 103 - Semaphore Pin, Task JWT and Locked Templates

## User Story

As the operator of a platform whose store starts Semaphore tasks on behalf of customers, I want one pinned Semaphore release with signed task tokens, and templates whose command, arguments, inventory and runner nobody can change at run time, so that OpenBao can tell which task asks for a secret and a customer value never becomes code.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, criteria 062:80, 062:91, 062:95 and 062:106) needs this core side.

### Today

- The IAM line pins Semaphore `v2.20.24` (`roles/web-app-semaphore/meta/services.yml:68-69`). The release v17.0.0 (`e36fd72a1d`) pins `v2.19.17` (`roles/web-app-semaphore/meta/services.yml:62` there), the "main v2.19.17" of the store's list.
- The server env sets no task-token option (`roles/web-app-semaphore/templates/env.j2`).
- Core builds every template body in one place. The body fixes `allow_override_args_in_task` to false and sets no `runner_tag`, no survey variables and no token parameters (`template_body`, `roles/web-app-semaphore/files/python/project.py:281-303`). The drift check compares app, playbook, arguments, inventory, repository, environments, type and that one flag (`same_template`, `project.py:305-323`).
- `deploy.sh` refuses any call with other than one argument (`roles/web-app-semaphore/files/shell/repository/deploy.sh:14-17`) and takes everything else from its environment (`deploy.sh:18-21`).

### Semaphore OSS v2.20.24

| Fact | Source |
| --- | --- |
| Task tokens: `SEMAPHORE_JWT_ENABLED`, `SEMAPHORE_JWT_ISSUER`, `SEMAPHORE_JWT_DEFAULT_TTL` (default `1h`), `SEMAPHORE_JWT_MAX_TTL` (default `24h`). | `JWTConfig` in [util/config.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/util/config.go) |
| The key set is served at `/.well-known/jwks.json` and answers 404 while tokens are off. | [api/jwks.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/jwks.go) |
| The token carries `iss`, `sub`, `aud`, `exp`, `nbf`, `iat`, `jti` and the integers `task_id`, `project_id`, `template_id`, plus `user_id` when a user started the task. A single audience is encoded as a plain string. | `TaskClaims`, `Audience` in [pkg/jwt/claims.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/pkg/jwt/claims.go) |
| A task gets its token as `SEMAPHORE_JWT`, and every task gets `SEMAPHORE_PROJECT_ID` and `SEMAPHORE_TASK_ID`. | `getEnvironmentENV`, `taskIdentityEnv` in [services/tasks/local_executor.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/local_executor.go) |
| A shell template gets, in order: the playbook, every environment secret of type `var` as `name=value`, the template arguments, every extra and survey variable as `name=value`, and the task's own arguments only when `allow_override_args_in_task` is set. A survey variable with target `env` becomes an environment variable instead. | `getShellArgs`, `getEnvironmentExtraVars`, `getSurveyEnvVars` in [services/tasks/local_executor.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/local_executor.go) |

So a survey variable without target `env`, or a `var` secret, reaches `deploy.sh` as an extra argument, which `deploy.sh:14-17` refuses (store criterion 062:95).

## Decisions

1. **Pin.** The IAM pin `v2.20.24` reaches core `main` with the IAM merge. A unit test holds the pin to one released tag of at least `v2.20.1`, the store's floor. A later bump keeps the store's contract test green (store criterion 062:182).
2. **Task tokens on.** The server sets `SEMAPHORE_JWT_ENABLED=true` and `SEMAPHORE_JWT_ISSUER` to Semaphore's canonical URL. `SEMAPHORE_JWT_DEFAULT_TTL` stays `1h`: a task logs in to OpenBao once at its start, and the OpenBao token then carries the rest of the run (105). OpenBao fetches the key set from `https://<semaphore domain>/.well-known/jwks.json` through the front proxy and, under `TLS_MODE` `self_signed`, trusts the deployment CA (105).
3. **Every template core creates is locked.** This covers the platform templates and the workspace templates. Each one has `allow_override_args_in_task` false, `allow_override_branch_in_task` false and `allow_parallel_tasks` false. Each one has the `runner_tag` of its project's runner (102). An Ansible-type template also gets `allow_override_inventory` false in its task parameters. Each one has `jwt_params` with `enabled` true and an `audience` naming the token's reader, `openbao`. The drift check compares all of these fields, so a template changed by hand is realigned by the next deploy or `workspace apply`.
4. **Inputs are survey variables with target `env`.** Every value a template accepts is a declared survey variable with target `env`; no template uses an environment secret of type `var`. Each script beside `deploy.sh` keeps refusing extra arguments and validates every variable it reads.
5. **No secret in a template.** The environment and the survey of a workspace template carry no secret value. A task reads its secrets from OpenBao with its token (105, 106). The foreign-server deploy of the platform keeps its vault password in its environment until 106 retires it.
6. **The workspace templates.** `workspace apply` (102) creates and realigns `deploy`, `backup`, `restart` and `update` in every workspace project. Their scripts come from the runner image, never from the workspace repository. Provisioning and destroying are templates of the platform's provision project (104). They run `tofu apply -auto-approve` and `tofu destroy -auto-approve` from a core script, so no Semaphore confirmation step exists for them (store item 2, "provision and destroy auto-approve").

Rejected:

- Semaphore's native OpenTofu app for provisioning: it runs the `.tf` files of the repository checkout, which the customer's repository would then supply.
- Template arguments for customer values: they reach the script as positional arguments outside any schema.

## Acceptance Criteria

### Pin

- [ ] `roles/web-app-semaphore/meta/services.yml` pins one released Semaphore tag of at least `v2.20.1`. A unit test fails on a lower tag, a branch, `latest` or a pre-release (`test_the_pin_is_a_release_of_at_least_2_20_1` in `tests/unit/python/roles/web-app-semaphore/meta/test_version_pin.py`).
- [ ] Core `main` carries that pin once the IAM line is merged: the same test runs on `main`.

### Task tokens

- [ ] The rendered server env sets `SEMAPHORE_JWT_ENABLED=true` and `SEMAPHORE_JWT_ISSUER` to the canonical Semaphore URL (`test_the_server_signs_task_tokens` in `tests/unit/python/roles/web-app-semaphore/templates/test_env.py`).
- [ ] On a deployed stack, `GET /.well-known/jwks.json` on the Semaphore origin answers 200 with at least one public key, both from the browser side and from inside the OpenBao container (`task token: the key set answers on the canonical origin` in `roles/web-app-semaphore/files/playwright/test-task-token.js`; the OpenBao side is proven by the login criteria of 105).
- [ ] A probe task of a template with tokens on receives `SEMAPHORE_JWT`. Its claims hold the task's `project_id`, `template_id` and `task_id`, the template's audience, and the configured issuer, and its signature verifies against the key set (`task token: a task receives a token for its own project and template` in `test-task-token.js`).

### Locked templates

- [ ] Every template body core builds has `allow_override_args_in_task`, `allow_override_branch_in_task` and `allow_parallel_tasks` false, a `runner_tag`, `jwt_params` with `enabled` true and the audience `openbao` and, for an Ansible template, `allow_override_inventory` false. One negative control per field must fail (`test_every_template_is_locked` and `test_negative_control_*` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).
- [ ] The drift check reports a template as changed when any of these fields differs, one case per field (`test_same_template_sees_every_locked_field` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).
- [ ] A task started through the API with its own `arguments`, another `inventory_id` or another branch runs with the template's values, shown by the command line the task log records (`locked template: run-time overrides do not reach the script` in `test-task-token.js`).
- [ ] A template changed by hand in the UI is back to its definition after the next deploy (`locked template: a deploy realigns a template changed by hand` in `test-task-token.js`).

### Inputs and secrets

- [ ] Every survey variable of every template core builds has target `env`, and no environment core builds holds a secret of type `var`. A planted survey variable without target and a planted `var` secret must fail (`test_every_input_reaches_the_script_as_env` and its two negative controls in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).
- [ ] A lint test fails when the environment or the survey of a workspace template holds a value read from `secrets.credentials` of any role, or a name declared as a credential in any role's `meta/secrets.yml`, the store's and ERPNext's included. Its negative controls plant both and must fail (`test_workspace_templates_carry_no_secret` and `test_the_check_catches_a_planted_credential` in `tests/lint/ansible/test_semaphore_template_secrets.py`).
- [ ] Each script a template runs (`deploy.sh`, `workspace.sh`, the provision script of 104 and the scripts behind `backup`, `restart` and `update`) exits non-zero on any extra argument and names it (`test_each_template_script_refuses_extra_arguments` in `tests/unit/python/roles/web-app-semaphore/files/test_template_scripts.py`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents the pin floor, the task token settings, the locked fields and the input rule (`test_the_readme_names_the_locked_fields` in `tests/unit/python/roles/web-app-semaphore/test_readme.py`).
