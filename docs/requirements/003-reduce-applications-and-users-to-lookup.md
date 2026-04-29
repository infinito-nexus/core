# 003 - Reduce `applications` and `users` to lookup-only access

## User Story

As a contributor, I want all access to application and user configuration to go through lookup plugins named `applications` and `users`, so that the project no longer has to generate, merge, and maintain the large `group_vars/all/05_applications.yml` and `group_vars/all/04_users.yml` dictionaries, and the complexity of the configuration surface is reduced.

## Acceptance Criteria

- [x] The files `group_vars/all/05_applications.yml` and `group_vars/all/04_users.yml` are deleted from the repository and are not recreated by any tooling.
- [x] The constructor stage ([01_constructor.yml](../../tasks/stages/01_constructor.yml)) no longer materializes merged `applications` or `users` facts via `ansible.builtin.set_fact`; the current `default_users | combine(...)` and `defaults_applications | merge_with_defaults(...)` tasks are removed instead of being replaced by new `set_fact` constants.
- [x] The lookup plugin names are exactly `applications` and `users`; no new `applications_all` or `users_all` lookup is introduced.
- [x] `lookup('applications')` returns the full merged applications mapping, and `lookup('users')` returns the full merged users mapping.
- [x] The `applications` lookup merges only two sources: defaults discovered from every `roles/*/config/main.yml` in the repository and overrides supplied through the normal Ansible variable `applications` in inventory, group vars, host vars, or role vars; no intermediate merged `applications` fact is created.
- [x] The `users` lookup merges only two sources: defaults discovered from every `roles/*/users/main.yml` in the repository and overrides supplied through the normal Ansible variable `users` in inventory, group vars, host vars, or role vars; no intermediate merged `users` fact is created.
- [x] The applications aggregation preserves the current logic from `cli/setup/applications/` (removed), including empty-config handling, deterministic ordering, placeholder rendering, `group_id` enrichment, and injection of per-application `users` references.
- [x] The users aggregation preserves the current logic from `cli/setup/users/` (removed), including merge/conflict handling, reserved-user handling, generated default fields, UID/GID allocation, uniqueness validation, and deterministic ordering.
- [x] Any tooling, make target, script, or role task whose purpose is to generate, render, merge, or rewrite `group_vars/all/05_applications.yml` or `group_vars/all/04_users.yml` is removed, and running such a generator is no longer possible from the project.
- [x] The steps in [setup.sh](../../scripts/setup.sh) that write `APPLICATIONS_OUT` (`group_vars/all/05_applications.yml`) or `USERS_OUT` (`group_vars/all/04_users.yml`) are removed.
- [x] The backing generators under `cli/setup/applications/` (removed) and `cli/setup/users/` (removed) are fully deleted after their still-needed aggregation logic has been moved behind the new lookup-only implementation.
- [x] If `make setup` has no remaining responsibilities after removing the applications/users generation steps, the target itself and its entry in the [Makefile](../../Makefile) are deleted; otherwise `make setup` remains but no longer generates applications or users data.
- [x] The applications lookup returns a dict keyed by `application_id` that is built by discovering and aggregating every `roles/*/config/main.yml` in the repository; the `application_id` is ALWAYS the role directory name (for example `roles/web-app-mailu/config/main.yml` is exposed as `applications['web-app-mailu']`), and there is no alternative key source.
- [x] `lookup('applications', '<application_id>')` returns the merged entry for that application.
- [x] The users lookup returns a dict keyed exactly like the current generated `default_users` mapping is keyed today, preserving the existing canonical user key behavior from the current aggregation logic.
- [x] The canonical key for a user is therefore the existing merged definition key from `roles/*/users/main.yml`, not the rendered `username` field inside the value, and no new keying scheme is introduced.
- [x] Inventory, group vars, host vars, and role vars continue to override user entries via `users.<canonical_user_key>` using that same existing canonical key behavior.
- [x] `lookup('users', '<canonical_user_key>')` returns the merged entry for that user.
- [x] When no override exists for a given `application_id` or canonical user key, the lookup returns the default value discovered from the role files.
- [x] The applications lookup returns the full set of applications across all roles, independent of `SERVICES_DISABLED` or `allowed_applications`; filtering by enabled or allowed apps remains the caller's responsibility and continues to use the existing mechanisms (for example `lookup('applications_current_play')`, which is not modified by this requirement).
- [x] When `lookup('applications', '<application_id>')` or `lookup('users', '<canonical_user_key>')` is called without a default and the entry is missing, the lookup raises an explicit error.
- [x] When `lookup('applications', '<application_id>', default)` or `lookup('users', '<canonical_user_key>', default)` is called and the entry is missing, the provided default is returned instead of raising.
- [x] Both lookup plugins cache only the aggregated defaults at module level so that the filesystem scan and YAML parsing of `roles/*/config/main.yml` and `roles/*/users/main.yml` happens at most once per Ansible worker process.
- [x] The merge with inventory-provided `applications` and `users` overrides runs on every lookup call even when the aggregated defaults are served from cache.
- [x] Each lookup plugin exposes a documented reset helper (for example `_reset_cache_for_tests()`) so that unit tests can guarantee a clean cache between test cases.
- [x] No role, playbook, template, filter plugin, lookup plugin, CLI command, validation script, test, or documentation file in the repository still references `defaults_applications` or `default_users`.
- [x] Every runtime reference to application configuration in roles, playbooks, templates, filter plugins, lookup plugins, and tests is replaced by `lookup('applications')` or by a wrapper that calls it. This includes dotted access (`applications.<id>`), bracket access (`applications['<id>']`), full-dict access (`{{ applications }}`), and pipeline/filter usage (for example `applications | dict2items`, `applications | combine(...)`). No task, playbook stage, or helper materializes a merged top-level `applications` fact for runtime use.
- [x] Every runtime reference to user configuration in roles, playbooks, templates, filter plugins, lookup plugins, and tests is replaced by `lookup('users')` or by a wrapper that calls it. This includes dotted access (`users.<name>`), bracket access (`users['<name>']`), full-dict access (`{{ users }}`), and pipeline/filter usage. No task, playbook stage, or helper materializes a merged top-level `users` fact for runtime use.
- [x] The contributor documentation under [contributing](../contributing/) is updated to describe the new lookup-only access pattern, how to add or override an application entry, and how to add or override a user entry, so that no contributor is tempted to re-introduce inline data in the two reduced files. See [applications.md](../contributing/artefact/files/plugins/lookup/applications.md) and [users.md](../contributing/artefact/files/plugins/lookup/users.md).
- [x] All documentation that references the removed generators (for example the [group_vars applications agent doc](../agents/files/group_vars/applications.md) and any contributor or agent docs that instruct running the generators) is updated to describe the new lookup-only workflow instead, so that no doc still tells the reader to regenerate the two files.
- [x] Unit tests cover the applications lookup for the full-dict case, the single-entry case, the override case, the strict missing-entry case, and the non-strict missing-entry case.
- [x] Unit tests cover the users lookup for the full-dict case, the single-entry case, the override case, the strict missing-entry case, and the non-strict missing-entry case.
- [x] Before iterating on [test-environment.yml](../../.github/workflows/test-environment.yml), the implementation is first iterated locally for `web-svc-dashboard` using the Role Loop defined in [role.md](../agents/action/iteration/role.md) until `web-svc-dashboard` deploys successfully at least once without errors.
- [x] The implementation is iterated locally on [test-environment.yml](../../.github/workflows/test-environment.yml) using the Workflow Loop defined in [workflow.md](../agents/action/iteration/workflow.md) (`ACT_WORKFLOW=.github/workflows/test-environment.yml ACT_JOB=test-environment ACT_MATRIX='dev_runtime_image:debian:bookworm' make act-workflow`) until the workflow passes end to end at least once without errors.

## Verification

- [x] Playwright end-to-end tests exist for the following five `web-app-*` roles, each living in the role's own `files/playwright.spec.js` and wired through the existing [test-e2e-playwright](../../roles/test-e2e-playwright) role so that merged `applications` and `users` data is exercised through a real browser session. Each spec MUST follow the baseline rules in [playwright.md](../contributing/actions/testing/playwright.md) (file layout, runner integration, `when to write` scope) and SHOULD fulfill the authoring rules in [playwright.spec.js.md](../agents/files/role/playwright.spec.js.md) and [playwright.env.j2.md](../agents/files/role/playwright.env.j2.md) wherever the application under test allows it:
  - [x] [web-app-keycloak](../../roles/web-app-keycloak)
  - [x] [web-app-dashboard](../../roles/web-app-dashboard)
  - [x] [web-app-matomo](../../roles/web-app-matomo)
  - [x] [web-app-openwebui](../../roles/web-app-openwebui)
  - [x] [web-app-discourse](../../roles/web-app-discourse)
- [x] Each of those Playwright specs MUST exercise the lookup pathway end to end by covering:
  - [x] a login flow that authenticates as a user sourced from `lookup('users')`, proving that merged user data reaches the rendered UI.
  - [x] an OIDC flow from [web-app-dashboard](../../roles/web-app-dashboard) through [web-app-keycloak](../../roles/web-app-keycloak) into the application under test (where the app supports OIDC), proving that `lookup('applications')` drives cross-app integration.
  - [x] at least one DOM assertion that a value originating from `applications['<application_id>']` is rendered in the UI (for example the canonical domain, display title, or a feature flag reflected in the DOM).
- [x] Each of those Playwright specs MUST assert the effective Content Security Policy of the rendered application, and MUST fail when the policy regresses or is missing. The assertions MUST cover:
  - [x] every directive that [csp_filters.build_csp_header](../../plugins/filter/csp_filters.py) currently emits, i.e. `default-src`, `connect-src`, `frame-ancestors`, `frame-src`, `script-src` (including `script-src-elem` and `script-src-attr`), `style-src` (including `style-src-elem` and `style-src-attr`), `font-src`, `worker-src`, `manifest-src`, `media-src`, and `img-src`. `form-action`, `base-uri`, and `object-src` are not emitted by the current helper and are therefore out of scope until the helper is extended.
  - [x] any `<meta http-equiv="Content-Security-Policy">` tag present in the rendered document, with both sources checked for parity when the application emits both.
  - [x] that the policy is enforced, not `Content-Security-Policy-Report-Only`.
  - [x] zero `securitypolicyviolation` events observed on `page` during the full test flow, captured via Playwright's `page.on('console')` and `page.on('pageerror')` listeners plus an explicit `window.addEventListener('securitypolicyviolation', ...)` hook.
- [x] Each of those Playwright specs MUST end in a logged-out state, MUST NOT contain `test.only` or `test.skip` in committed code, and MUST emit Playwright traces, screenshots, and video for failed runs so CI artifacts can be used for triage.
- [x] The five Playwright specs MUST run in the CI gate (for example as a matrix job in [test-environment.yml](../../.github/workflows/test-environment.yml) or an equivalent gating workflow), MUST upload their failure artifacts to the CI run, and MUST block the merge when any of them fails.

### Clarifications

The following decisions bind the Verification work above. They were captured during implementation and supersede ambiguous reads of the checkboxes.

- **Dashboard spec scope**: extend the existing [playwright.spec.js](../../roles/web-app-dashboard/files/playwright.spec.js); do NOT rewrite.
- **Keycloak personas and realms**: the Keycloak super administrator MUST sign in to the master realm, the `biber` and `administrator` personas MUST sign in to the normal realm. All three flows MUST use the Keycloak login interface directly, NOT an OIDC round-trip through another app.
- **Matomo persona**: the `administrator` MUST sign in with the local Matomo login, NOT via OIDC.
- **CSP threshold rule**: a directive is asserted if and only if [csp_filters.build_csp_header](../../plugins/filter/csp_filters.py) emits it. Missing directives that are expected by the helper MUST cause the spec to fail. Directives that the helper does not emit today (`form-action`, `base-uri`, `object-src`) are out of scope until the helper is extended.
- **CSP gap handling**: when an app is missing a directive that the helper is supposed to emit, the app MUST be fixed in the same PR (for example via `webserver_extra_configuration` or the nginx vhost). No follow-up ticket SHOULD be used as an escape hatch.
- **Iteration mode**: this work uses the Role Loop from [role.md](../agents/action/iteration/role.md). The Workflow Loop is NOT used.
- **CI gate and failure artifacts**: covered transitively by the Role Loop. No separate `actions/upload-artifact` wiring is added by this requirement because no new CI workflow is introduced.
- **SERVICES\_DISABLED scope**: the Role Loop for this requirement runs against the full stack; no services are disabled.
- **Batching**: all five target apps are deployed together via `make deploy-fresh-purged-apps APPS="web-app-keycloak web-app-dashboard web-app-matomo web-app-openwebui web-app-discourse" FULL_CYCLE=true` as the baseline. Inner spec-only iteration uses [rerun-spec.sh](../../scripts/tests/e2e/rerun-spec.sh). Role-asset changes trigger `make deploy-reuse-kept-apps APPS=<role>`. Final confirmation for each role uses `make deploy-fresh-purged-apps APPS=<role>`.
- **DOM assertion value**: the canonical domain sourced from `applications['<application_id>']` is the preferred value for the UI-visible assertion.
- **Personas per spec (where applicable)**: `biber` and `administrator` MUST both be covered where the application allows it. Both personas are sourced via `lookup('users', '<canonical_user_key>')`; `biber` is provisioned through the [development inventory](../../inventories/development/default.yml) analogously to `administrator`.
- **Keycloak super-admin credential source**: the master-realm super admin MUST authenticate with `KEYCLOAK_PERMANENT_ADMIN_USERNAME` and `KEYCLOAK_PERMANENT_ADMIN_PASSWORD` from the [Keycloak role vars](../../roles/web-app-keycloak/vars/main.yml). This is the documented exception to the general "login via `lookup('users')`" rule because the permanent admin is not a users-lookup entry.
