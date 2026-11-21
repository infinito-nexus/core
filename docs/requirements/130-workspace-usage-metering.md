# 130 - Workspace Usage Metering

## User Story

As the operator of the Infinito.Nexus store, I want every workspace to count the active people in the Keycloak of its deployed instance once a day through a read-only core template, so that the store bills user accounts from the monthly maximum of those counts while the customer manages their users directly in their own Keycloak and no store or platform credential can change an instance's users.

## Context (2026-11-14, IAM store round)

- 101, 123 and 125 (deleted, see Git history) let the store list, create and delete the users of a workspace's instance for the store's Users tab (`infinito-nexus/gui`, requirement 058).
- Members of a workspace and their rights already live in the platform realm: the organization `ws-<id>` and its role groups ([107](107-keycloak-organizations-workspace-roles-and-one-client-per-consumer.md)).
- A Users tab duplicates the instance's own Keycloak console and gives the store write access to every instance's users.

## Decisions (operator, 2026-11-14)

Binding; not reopened by this document.

1. **No user management through the store.** The customer manages the members of their workspace and their rights in the platform realm (107) and the users of their instance directly in the instance's Keycloak. 101, 123, 125 and the store's Users tab are dropped, their code and tests included.
2. **What is billed.** Once a day the template counts the active people of each instance: the enabled users of the instance's application realm, without service-account users and without the technical administrator of the `master` realm. The store bills the highest daily count of the month.
3. **A locked `usage` template.** `workspace apply` ([102](102-one-semaphore-runner-per-workspace.md)) creates one locked template `usage` per workspace project, locked like every core template ([103](103-semaphore-pin-task-jwt-and-locked-templates.md)), with a daily Semaphore schedule. `destroy` removes both. The template takes no survey and no argument; it counts every host of the workspace's inventory whose Keycloak turns the usage client on.
4. **An own read-only client.** `services.keycloak.usage_client.enabled` makes the deploy create a confidential client `usage` whose service account holds `view-users` of `realm-management` and nothing else; turning it off deletes the client. Its secret is `credentials.usage_client_secret`, an OpenBao reference in the workspace's tenant path ([106](106-infinito-deploy-reads-credentials-from-openbao.md) decision 2). It lives in the workspace's own tenant path, where the `deploy` that configures the client and the `usage` task read it with their own task tokens under the workspace's role ([105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decision 3); every task of the workspace already reads the instance's credentials, so a binding to the `usage` template alone would narrow nothing. The store writes it and never reads it back (105 decision 6), no other workspace reads it, and it never reaches an argument, the environment, a log or the task output. The instance's HTTPS port has to be a pair of `WORKSPACE_TARGETS` (102 decision 6).
5. **Core measures, the store bills.** The last output line of a `usage` task is one JSON object: `workspace`, `counted_at` (UTC, ISO 8601) and `hosts`, a list of `{host, realm, active_users}`. The store reads it like every task output, keeps each daily value in its own database and computes the monthly maximum. Core keeps no billing state.

## Acceptance Criteria

### Removal

- [x] The directory client of 101, the `directory` template of 123 and the OpenBao binding of 125 are gone with their tasks, scripts, credentials, variants, specs and tests, and the three requirement files are deleted; no file outside `docs/requirements/` names `directory_client`, `directory_client_secret` or the `directory` template.
- [x] 102, 103, 105 and 107 no longer refer to 101, 123 or 125; where they named the directory operations, they name this requirement.

### Usage client

- [x] With the switch on, the deploy creates the client `usage` and grants its service account exactly `view-users`; a second deploy changes nothing; with the switch off, the deploy deletes it. A negative control that grants `manage-users` must fail (`test_the_usage_client_holds_view_users_only` and its control in `tests/unit/python/roles/web-app-keycloak/test_usage_client_tasks.py`).
- [ ] On a deployed instance, a client-credentials token of `usage` lists users and gets `403` on creating, changing and deleting a user and on `PUT /admin/realms/<realm>` (`usage client: reads users and changes nothing` in `roles/web-app-keycloak/files/playwright/test-usage-client.js`).

### Count

- [x] The count includes enabled users and skips disabled users, service-account users and the `master` realm administrator; a negative control that counts every user must fail (`test_the_count_is_active_people_only` and its control in `tests/unit/python/roles/web-app-keycloak/files/test_usage.py`).
- [x] The last output line has exactly `workspace`, `counted_at` and `hosts`, each host entry exactly `host`, `realm` and `active_users` (`test_usage_ends_with_its_result` in `tests/unit/python/roles/web-app-semaphore/files/test_usage_sh.py`).
- [x] Neither the task token nor the usage client secret appears in the stdout, stderr, argv or environment of a run, a refused run or a failed run; a control that prints the secret must fail (`test_usage_prints_no_secret` and its control in `test_usage_sh.py`).
- [ ] On an instance deployed to the shared target through the workspace's `deploy` template with the usage client on, the count equals its enabled people, rises by one after a probe user is created and falls back after the probe user is disabled (`usage: counts the active people of the instance` in `roles/web-app-semaphore/files/playwright/test-workspace-usage.js`).

### Template and schedule

- [ ] `workspace apply` creates exactly one locked `usage` template per workspace project with no survey and no argument, and one daily schedule for it; a second `apply` changes nothing and `destroy` removes both (`test_the_usage_template_is_fixed` and its control in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`; `usage: apply schedules the daily count` in `test-workspace-usage.js`).
- [ ] A `usage` task reads `credentials.usage_client_secret` from its own workspace's tenant path, and a `usage` task of another workspace and the store's AppRole are refused on it (`usage login: a usage task reads only its own workspace's secret` in `roles/web-app-semaphore/files/playwright/test-workspace-logins.js`).
- [x] A `usage` task for a host whose inventory turns the usage client off reports that host with `active_users` null and makes no call to it (`test_a_host_without_the_usage_client_is_reported_unmeasured` in `test_usage_sh.py`).

### Documentation

- [x] The [web-app-semaphore README](../../roles/web-app-semaphore/README.md) documents the `usage` template, its schedule and its output line; the [web-app-keycloak README](../../roles/web-app-keycloak/README.md) documents the usage client switch.

## Tests

- `tests/unit/python/roles/web-app-keycloak/test_usage_client_tasks.py`: switch on and off, the single role grant, idempotency, the `manage-users` control.
- `tests/unit/python/roles/web-app-keycloak/files/test_usage.py`: the count rule and its control.
- `tests/unit/python/roles/web-app-semaphore/files/test_usage_sh.py`: the output line, no secret in any channel, the unmeasured host.
- `tests/unit/python/roles/web-app-semaphore/files/test_project.py`: the locked template and its schedule.
- Live: `test-usage-client.js`, `test-workspace-usage.js`, `test-workspace-logins.js`.

## Cross-linking

- Replaces: 101, 123 and 125 (deleted, see Git history).
- Builds on: [102](102-one-semaphore-runner-per-workspace.md), [103](103-semaphore-pin-task-jwt-and-locked-templates.md), [105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md), [106](106-infinito-deploy-reads-credentials-from-openbao.md), [107](107-keycloak-organizations-workspace-roles-and-one-client-per-consumer.md), [127](127-platform-deploy-fixture.md).
- Store side: `infinito-nexus/gui` requirement 058 drops its Users tab and bills from the `usage` output.
