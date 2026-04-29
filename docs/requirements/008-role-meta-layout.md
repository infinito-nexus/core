# 008 - Role Meta Layout Refactoring

## User Story

As a contributor, I want every role's metadata to live under predictable,
purpose-named files inside `meta/` so that the on-disk layout reflects what
each file describes, the monolithic `config/main.yml` is split into
single-responsibility files, and per-service configuration is inlined under the
service definition that owns it.

## Background

Today every role uses three generically-named entry files:

| Current path                       | Purpose                                                             |
|------------------------------------|---------------------------------------------------------------------|
| `roles/<role>/schema/main.yml`     | Credential schema consumed by the inventory credential generator.   |
| `roles/<role>/users/main.yml`      | Role-local user definitions consumed by `utils/cache/users.py`.     |
| `roles/<role>/config/main.yml`     | Role-local payload consumed by `utils/cache/applications.py`.       |

`config/main.yml` is a grab-bag: across the repository it carries 20+ different
top-level keys (`compose`, `server`, `rbac`, `credentials`, `plugins`,
`accounts`, `alerting`, `email`, `ldap`, `scopes`, `default_quota`,
`plugins_enabled`, `site_name`, …). The file name `main.yml` also collides
semantically with Ansible's auto-loaded `meta/main.yml`, `tasks/main.yml`, etc.

The new layout consolidates every "metadata about the role" file under `meta/`,
splits `config/main.yml` along its real semantic seams, and inlines all
service-specific configuration under the service entity it belongs to inside
`meta/services.yml`.

## Target Layout

After this refactor every role's metadata lives exclusively under `meta/`:

| New file              | Contents                                                                                                                                                       |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `meta/main.yml`       | **Unchanged.** Ansible Galaxy info / `dependencies:` / `run_after:` (per requirement 002).                                                                     |
| `meta/schema.yml`     | Merged credential schema. Replaces `schema/main.yml` *and* the `credentials:` top-level block from `config/main.yml`. See "Schema Format" below.               |
| `meta/users.yml`      | Role-local user definitions. Direct rename of `users/main.yml`.                                                                                                |
| `meta/server.yml`     | Content of the `server:` top-level block from `config/main.yml` (CSP, `domains`, `status_codes`). The `server:` wrapper key is dropped — file-root IS the former `server:` content. |
| `meta/rbac.yml`       | Content of the `rbac:` top-level block from `config/main.yml`. The `rbac:` wrapper key is dropped — file-root IS the former `rbac:` content.                  |
| `meta/services.yml`   | Content of `compose.services:` from `config/main.yml` **plus** every other former top-level key (`plugins`, `accounts`, `scopes`, `email`, …) inlined under the corresponding service entry. File-root is a map keyed by `<entity_name>` — no `services:` and no `compose:` wrapper. |
| `meta/volumes.yml`    | Content of `compose.volumes:` from `config/main.yml`. File-root is a map keyed by volume name — no `volumes:` and no `compose:` wrapper.                       |

The role-level directories `schema/`, `users/`, and `config/` MUST be removed
once their contents are migrated. Ansible only auto-loads `meta/main.yml`; the
other `meta/<topic>.yml` files are read exclusively by the project's own
loaders (`utils/cache/applications.py`, `utils/cache/users.py`,
`utils/manager/inventory.py`).

### File-Root Convention

Every `meta/<topic>.yml` file (except `meta/main.yml`, which keeps Galaxy
semantics, and `meta/schema.yml`, which is processed by `apply_schema()`)
follows the rule:

> **The file's content IS the value of `applications.<app>.<topic>`. There is
> NO wrapping key matching the filename.**

So `meta/services.yml` MUST NOT have a top-level `services:` key wrapping its
content; `meta/volumes.yml` MUST NOT have a top-level `volumes:` key; same for
`meta/server.yml`, `meta/rbac.yml`, `meta/users.yml`. The filename alone fixes
the path prefix in the materialised application tree, which keeps consumer
paths short and predictable (no redundant `compose.…` prefixes).

### Services Inlining

All top-level keys of the old `config/main.yml` *except* `compose:`, `server:`,
`rbac:`, and `credentials:` MUST be inlined into `meta/services.yml` under
`<entity_name>.<key>`, where `<entity_name>` is the value returned by
`get_entity_name(role_name)` (per requirement 002).

Inlined keys observed today (non-exhaustive): `plugins`, `plugins_enabled`,
`email`, `ldap`, `accounts`, `scopes`, `alerting`, `addons`, `languages`,
`company`, `default_quota`, `legacy_login_mask`, `site_name`, `token`,
`modules`, `network`, `performance`, `preload_models`, `provision`.

`compose.volumes:` is *not* inlined into services — it moves into its own
`meta/volumes.yml` (volumes are role-wide, not per-service).

**Example** — `web-app-matomo` (entity_name `matomo`):

```yaml
# Before: roles/web-app-matomo/config/main.yml
site_name: "{{ ... }}"
performance:
  workers: 4
compose:
  services:
    matomo:
      image: matomo
  volumes:
    data: matomo_data

# After: roles/web-app-matomo/meta/services.yml  (file-root IS the services map)
matomo:
  image: matomo
  site_name: "{{ ... }}"
  performance:
    workers: 4

# After: roles/web-app-matomo/meta/volumes.yml  (file-root IS the volumes map)
data: matomo_data
```

### Schema Format (`meta/schema.yml`)

`meta/schema.yml` consolidates two structures that today share the
`credentials:` top-level key but live in different files:

1. The credential **schema definitions** from `schema/main.yml` (today flat,
   e.g. `alerting_telegram_bot_token: { description, algorithm, validation }`).
2. The credential **runtime values** from the `credentials:` block of
   `config/main.yml` (today nested, e.g. `recaptcha.key`, `recaptcha.secret`).

The unified schema MUST support:

- **Nested keys.** The flat-keys-only restriction of `schema/main.yml` is
  lifted; e.g. `recaptcha.key` and `recaptcha.secret` remain nested.
- **`algorithm:` defaults to `plain`** when the field is omitted.
- **`default:` (new, optional)** — a Jinja string used as the credential's
  value when the inventory does not provide one.
  - `default:` is **NOT rendered at inventory creation time.** The literal
    Jinja string is written verbatim into the inventory so that referenced
    variables (`CAPTCHA.RECAPTCHA.KEY`, `lookup(...)`, …) resolve only at
    deploy/runtime when those variables are actually defined.
  - `default:` values are **NOT validated.** `validation:` only applies to
    user-provided values; the schema default is exempt.
  - When `default:` is present, the credential generator MUST NOT generate a
    new value via `algorithm:`; it writes the literal `default:` string
    verbatim.

**Example** — merging keycloak's `config/main.yml` runtime credentials into
`meta/schema.yml`:

```yaml
# Before: roles/web-app-keycloak/config/main.yml (excerpt)
credentials:
  recaptcha:
    key:    "{{ CAPTCHA.RECAPTCHA.KEY    | default('') }}"
    secret: "{{ CAPTCHA.RECAPTCHA.SECRET | default('') }}"

# After: roles/web-app-keycloak/meta/schema.yml
credentials:
  recaptcha:
    key:
      description: "Google reCAPTCHA site key."
      algorithm:   plain
      default:     "{{ CAPTCHA.RECAPTCHA.KEY | default('') }}"
    secret:
      description: "Google reCAPTCHA secret key."
      algorithm:   plain
      default:     "{{ CAPTCHA.RECAPTCHA.SECRET | default('') }}"
```

Existing flat schema entries are unchanged in shape:

```yaml
# After: roles/web-app-prometheus/meta/schema.yml
credentials:
  alerting_telegram_bot_token:
    description: "Telegram bot token for Alertmanager notifications."
    algorithm:   token
    validation:  non_empty_string
  alerting_mattermost_webhook_url:
    description: "Mattermost incoming webhook URL for Alertmanager."
    algorithm:   url
    validation:  non_empty_string
```

### Consumer Path Rewrites

The `compose.` prefix is dropped from every consumer path. Three rewrite
patterns apply:

| Old path                                     | New path                                | Why                                         |
|----------------------------------------------|-----------------------------------------|---------------------------------------------|
| `compose.services.<entity>.<…>`              | `services.<entity>.<…>`                 | `meta/services.yml` IS the services map.    |
| `compose.volumes.<key>`                      | `volumes.<key>`                         | `meta/volumes.yml` IS the volumes map.      |
| `<top-level-key>.<…>` (e.g. `plugins.…`, `accounts.…`, `scopes.…`, `site_name`, `performance.…`, …) | `services.<entity>.<top-level-key>.<…>` | Long-tail keys inline under the role's primary service. |

Schema-supplied `credentials.*` paths are unchanged because `apply_schema()`
continues to expand them to `applications.<app>.credentials.<…>`.

**Examples:**

```jinja
{# Old: compose.services.<entity>.<…> #}
LISTMONK_VERSION="{{ lookup('config', application_id, 'compose.services.listmonk.version') }}"
{# New #}
LISTMONK_VERSION="{{ lookup('config', application_id, 'services.listmonk.version') }}"

{# Old: compose.volumes.<key> #}
MASTODON_VOLUME="{{ lookup('config', application_id, 'compose.volumes.data') }}"
{# New #}
MASTODON_VOLUME="{{ lookup('config', application_id, 'volumes.data') }}"

{# Old: top-level inline #}
{{ lookup('config', application_id, 'plugins.oidc.version') }}
{# New (entity_name = pretix) #}
{{ lookup('config', application_id, 'services.pretix.plugins.oidc.version') }}
```

**Lookup plugins** that hard-code `compose.services.<…>` / `compose.volumes.<…>`
config paths and MUST be updated:

- `plugins/lookup/config.py` (the `config` lookup itself)
- `plugins/lookup/service.py` (`compose.services`, `compose.services.<key>.<flag>`)
- `plugins/lookup/database.py` (`compose.services.<dbtype>.{name,version}`)
- `plugins/lookup/oidc_flavor.py` (`compose.services.{oidc.flavor, ldap.enabled}`)
- `plugins/lookup/native_metrics_apps.py` (`compose.services.prometheus.native_metrics.enabled`)
- `plugins/lookup/active_alertmanager_channels.py` (`compose.services.prometheus.communication.channel`)
- `plugins/lookup/prometheus_integration_active.py` (`compose.services.prometheus.enabled`)
- `plugins/lookup/nginx.py` (`compose.volumes.{www,nginx}`)

**Role-internal `vars/main.yml`** files that hard-code `compose.services.<entity>.<…>`
or `compose.volumes.<…>` (non-exhaustive; full sweep required):
`web-app-pgadmin`, `web-app-listmonk`, `web-app-mastodon`, …

There MUST be no aliasing or "hoisting" layer in the loader that re-exposes
the old `compose.…` or top-level paths.

## Acceptance Criteria

### File moves

- [ ] Every existing `roles/<role>/schema/main.yml` is migrated to
      `roles/<role>/meta/schema.yml` and merged with the `credentials:` block
      from the same role's `config/main.yml` (if any) per the "Schema Format"
      rules. The `schema/` directory is removed for every affected role.
- [ ] Every existing `roles/<role>/users/main.yml` is moved to
      `roles/<role>/meta/users.yml`. The `users/` directory is removed for
      every affected role.
- [ ] Every existing `roles/<role>/config/main.yml` is split into
      `meta/server.yml`, `meta/rbac.yml`, `meta/services.yml`, `meta/volumes.yml`,
      and (for the `credentials:` block) absorbed into `meta/schema.yml`. The
      `config/` directory is removed for every affected role.
- [ ] `meta/services.yml`, `meta/volumes.yml`, `meta/server.yml`,
      `meta/rbac.yml`, and `meta/users.yml` MUST NOT contain a wrapping
      top-level key matching the file basename. The file's content IS the
      value of `applications.<app>.<topic>` directly.
- [ ] No role retains any of `schema/main.yml`, `users/main.yml`,
      `config/main.yml`, `schema/`, `users/`, or `config/` after the refactor.
- [ ] `meta/main.yml` is preserved verbatim and coexists with the new
      `meta/<topic>.yml` files.

### Services inlining

- [ ] All top-level keys of the old `config/main.yml` other than `compose:`,
      `server:`, `rbac:`, and `credentials:` are inlined under
      `<entity_name>.<key>` in `meta/services.yml`.
- [ ] The `compose.volumes:` block is migrated to its own `meta/volumes.yml`
      file (file-root IS the volumes map; no `volumes:` wrapper).
- [ ] `<entity_name>` is derived via `get_entity_name(role_name)` (the same
      function used by `sys-utils-service-loader` per requirement 002).
- [ ] `meta/services.yml` is a map keyed by `<entity_name>` at file root —
      no `services:` wrapper, no `compose:` wrapper.

### Schema format

- [ ] `meta/schema.yml` accepts nested credential keys (e.g.
      `credentials.recaptcha.key`).
- [ ] `meta/schema.yml` accepts an optional `default:` field per credential.
- [ ] When `algorithm:` is omitted, the credential generator treats the entry
      as `algorithm: plain`.
- [ ] Credentials with `default:` are NOT validated, regardless of any
      `validation:` set on sibling entries.
- [ ] Credentials with `default:` are written verbatim (as Jinja literals)
      into the generated inventory; the credential generator MUST NOT render
      the Jinja, generate a value via `algorithm:`, or strip whitespace.
- [ ] If a single role defines the same credential key in both
      `schema/main.yml` and the `credentials:` block of `config/main.yml`, the
      migration MUST stop and surface the collision instead of silently
      merging.

### Code consumers

- [ ] All Python consumers that hard-code the old paths are updated. At
      minimum:
      - `utils/manager/inventory.py` (`schema/main.yml` → `meta/schema.yml`)
      - `utils/applications/config.py` (`schema/main.yml` → `meta/schema.yml`)
      - `utils/cache/users.py` (`*/users/main.yml` → `*/meta/users.yml`)
      - `utils/cache/applications.py` (`*/config/main.yml` →
        per-topic load of `meta/server.yml` → `applications.<app>.server`,
        `meta/rbac.yml` → `applications.<app>.rbac`,
        `meta/services.yml` → `applications.<app>.services`,
        `meta/volumes.yml` → `applications.<app>.volumes`,
        plus the schema-applied `meta/schema.yml` →
        `applications.<app>.credentials`. Variants from `meta/variants.yml`
        deep-merge over the assembled payload, just as they used to over
        `config/main.yml`.)
      - `utils/cache/base.py`
      - `utils/docker/version_updater.py`
      - `utils/docker/image/discovery.py`
      - `plugins/filter/native_metrics_target.py`
      - `plugins/lookup/config.py` (the `config` lookup itself)
      - `plugins/lookup/service.py`
      - `plugins/lookup/database.py`
      - `plugins/lookup/oidc_flavor.py`
      - `plugins/lookup/native_metrics_apps.py`
      - `plugins/lookup/active_alertmanager_channels.py`
      - `plugins/lookup/prometheus_integration_active.py`
      - `plugins/lookup/nginx.py`
      - `plugins/lookup/application_gid.py`
      - `plugins/lookup/rbac_group_path.py`
      - `cli/fix/docker_image_versions/__main__.py`
      - `cli/deploy/development/inventory.py`
      - `cli/meta/applications/resolution/combined/role_introspection.py`
      - `cli/meta/applications/resolution/services/resolver.py`
      - `cli/meta/applications/ressources/__main__.py`
      - `cli/meta/applications/sufficient_storage/__main__.py`
      - `cli/create/inventory/services_disabler.py`
      - `cli/create/credentials/__main__.py`
      - any other consumer discovered during migration that references
        `schema/main.yml`, `users/main.yml`, or `config/main.yml`.
- [ ] No legacy fallback to the old paths is implemented; the new paths are
      the single source of truth.

### Consumer-path rewrites

- [ ] Every reference (Python lookup plugin, Jinja template, `vars/*.yml`,
      task file) that reads `compose.services.<entity>.<…>` is rewritten to
      `services.<entity>.<…>`.
- [ ] Every reference that reads `compose.volumes.<key>` is rewritten to
      `volumes.<key>`.
- [ ] Every reference to a former top-level key of `config/main.yml`
      (e.g. `'plugins.…'`, `'accounts.…'`, `'scopes.…'`, `'site_name'`,
      `'plugins_enabled'`, `'default_quota'`, `'legacy_login_mask'`,
      `'performance.…'`, `'modules.…'`, `'network.…'`, `'addons.…'`,
      `'preload_models.…'`, `'provision.…'`, `'languages.…'`, `'email.…'`,
      `'ldap.…'`, `'company.…'`, `'alerting.…'`, `'token.…'`) is rewritten to
      `'services.<entity_name>.<…>'`.
- [ ] Schema-supplied `credentials.*` consumer paths are unchanged because
      `apply_schema()` continues to populate `applications.<app>.credentials.<…>`.
- [ ] No aliasing/hoisting layer is introduced in the loader to keep old
      `compose.…` or top-level paths working. A repository-wide `grep` for
      `'compose.services.'` and `'compose.volumes.'` MUST return zero matches
      after the refactor.

### Tests

- [ ] All affected unit and integration tests are updated to the new paths,
      including (at minimum) the tests under `tests/unit/utils/cache/`,
      `tests/unit/cli/`, `tests/unit/plugins/`, `tests/integration/config/`,
      `tests/integration/inventory/`, `tests/integration/docker/`,
      `tests/integration/services/`, and `tests/lint/ansible/`.
- [ ] Test fixtures that materialise role directories on disk
      (e.g. `tests/unit/utils/cache/test_users_module.py`,
      `tests/unit/utils/cache/test_data.py`,
      `tests/unit/cli/test_inventory_manager.py`,
      `tests/unit/cli/create/test_credentials.py`,
      `tests/unit/plugins/lookup/test_application_gid.py`) write to the new
      paths only.
- [ ] New unit tests cover the `default:` field behaviour: not rendered,
      not validated, written verbatim, suppresses `algorithm:`-based
      generation.
- [ ] New unit tests cover nested credential keys in `meta/schema.yml`.
- [ ] A new lint test under `tests/lint/` MUST fail if any role still
      contains `schema/main.yml`, `users/main.yml`, or `config/main.yml`, and
      MUST fail if any source file references these strings outside of
      (a) this requirement file and (b) historical changelogs.

### Documentation

- [ ] Documentation under `docs/contributing/` and `docs/agents/` that
      mentions the old paths is updated. Specifically:
      - any file under `docs/contributing/design/services/` that references
        `config/main.yml` is updated to point at `meta/services.yml` (or the
        appropriate `meta/<topic>.yml`);
      - any file that references `schema/main.yml` is updated to point at
        `meta/schema.yml`;
      - any file that references `users/main.yml` is updated to point at
        `meta/users.yml`;
      - the new `default:` schema field, the merge of runtime credentials
        into `meta/schema.yml`, and the services-inlining rule are documented
        in `docs/contributing/design/services/`.
- [ ] `roles/<role>/AGENTS.md` and `roles/<role>/README.md` files are updated
      where they reference the old paths.
- [ ] `.github/PULL_REQUEST_TEMPLATE/server.md` is updated (the
      `schema/main.yml` checklist row).
- [ ] Comments and docstrings inside `roles/<role>/vars/main.yml`,
      `roles/<role>/tasks/**/*.yml`, and `roles/<role>/meta/variants.yml`
      that mention `config/main.yml`, `schema/main.yml`, or `users/main.yml`
      are updated to the new paths.

### Atomicity & validation

- [ ] The migration MUST land as a single atomic change set: file moves,
      consumer-code updates, consumer-path rewrites, test updates, and doc
      updates ship together so no intermediate commit leaves the tree in a
      half-migrated state.
- [ ] After the refactor, a repository-wide `grep` for `schema/main.yml`,
      `users/main.yml`, and `config/main.yml` MUST return zero matches outside
      of (a) this requirement file and (b) historical changelogs.
- [ ] `make test` passes after the refactor with no skipped suites.
- [ ] Every file and role touched by this refactoring is also simplified and
      refactored where possible, following the principles in
      [principles.md](../contributing/design/principles.md).

## Validation Apps

The following selection covers all relevant migration patterns and MUST deploy
end to end after the refactor:

| App                  | Why it's in the validation set                                                                 |
|----------------------|------------------------------------------------------------------------------------------------|
| `web-svc-cdn`        | Frontend svc with canonical aliases; baseline from req-002.                                    |
| `web-svc-file`       | Simplest frontend svc; baseline auto-detection.                                                |
| `web-app-dashboard`  | Frontend web-app consuming multiple services.                                                  |
| `svc-db-postgres`    | Database as a regular service (req-002).                                                        |
| `svc-db-mariadb`     | MariaDB as a regular service (req-002).                                                         |
| `web-app-matomo`     | Top-level `site_name`, `performance` → inline test.                                            |
| `web-app-gitea`      | RBAC + Keycloak (OIDC) dependency.                                                              |
| `web-app-prometheus` | Schema-only credentials (`alerting_telegram_bot_token`, …) → `meta/schema.yml` test.            |
| `web-app-keycloak`   | RBAC + runtime `credentials.recaptcha.{key,secret}` → schema-merge + `default:` test.           |
| `web-app-pretix`     | Top-level `plugins:` → `services.pretix.plugins` inline test.                                   |
| `web-app-xwiki`      | Top-level `plugins:` + `features:` → inline test.                                               |
| `web-app-listmonk`   | Runtime `credentials.hcaptcha.{key,secret}` → `default:` test (consumer in `vars/main.yml`).    |
| `web-app-espocrm`    | Runtime `credentials.recaptcha.{key,secret}` → `default:` test.                                 |
| `web-app-nextcloud`  | Most complex web-app: MariaDB + Keycloak + many services + `plugins:` → end-to-end stress test. |
| `web-app-wordpress`  | Multisite role with config-heavy `vars/main.yml` (req-005); exercises consumer-path rewrites.   |
| `web-app-yourls`     | Minimal app surface; baseline regression check.                                                 |

```bash
APPS="web-svc-cdn web-svc-file web-app-dashboard svc-db-postgres svc-db-mariadb web-app-matomo web-app-gitea web-app-prometheus web-app-keycloak web-app-pretix web-app-xwiki web-app-listmonk web-app-espocrm web-app-nextcloud web-app-wordpress web-app-yourls" \
  make deploy-fresh-purged-apps
```

## Migration Notes

- The Ansible-reserved `meta/main.yml` is unrelated to the new
  `meta/<topic>.yml` files. Ansible only auto-loads `meta/main.yml`; the rest
  is read by the project's own loaders.
- `default:` values are intentionally NOT rendered at inventory creation time.
  The Jinja literal is written verbatim so that runtime variables resolve at
  deploy time, not at inventory generation. This is by design and the loader
  MUST preserve the literal string.
- The schema-key collision between `schema/main.yml` `credentials:` and
  `config/main.yml` `credentials:` is benign at the time of writing — no role
  defines the same credential name in both. If a collision arises during
  migration, the requirement is violated and the agent MUST stop and surface
  it.
- `meta/variants.yml` (used today by `svc-ai-ollama`, `web-app-phpmyadmin`)
  is **not** moved or renamed; it stays at its current path. The variants
  loader (`utils/cache/applications.py:_build_variants`) MUST deep-merge
  variant payloads over the new assembled application payload (server +
  rbac + services + volumes + apply_schema'd credentials) instead of over
  the old `config/main.yml`.

## Prerequisites

Before starting any implementation work, you MUST read [AGENTS.md](../../AGENTS.md)
and follow all instructions in it.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications
only when a decision is genuinely ambiguous and would otherwise block progress;
default to the intent already captured in this document and proceed. Avoid
back-and-forth questions on choices that are already specified above
(layout, schema format, consumer-path rewrites, atomicity).

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Land the refactor in a single atomic branch:
   1. Update the loaders/consumers (`utils/cache/*`, `utils/manager/*`,
      `utils/applications/*`, `plugins/*`, `cli/*`) to read from the new
      paths and to apply the new schema rules (`default:`, nested keys,
      implicit `algorithm: plain`).
   2. Rename and split files across all roles in one mechanical pass.
   3. Rewrite all consumer paths (`lookup('config', …)`, Jinja templates,
      `vars/*.yml`) to the new `services.<entity_name>.<…>` form.
   4. Update tests and fixtures to match.
   5. Update docs, role-level READMEs, `AGENTS.md` files, and the PR template.
   6. Add the lint test that prevents the old paths from coming back.
3. Run `make test` until green.
4. Run the validation deploy listed above.

## Final Iteration

After the atomic refactor branch is in place and `make test` is green, the
agent MUST iterate end-to-end following [Role Loop](../agents/action/iteration/role.md)
against the following three apps (in order):

1. `web-app-nextcloud` — most complex; MariaDB + Keycloak + many services + `plugins:`.
2. `web-app-wordpress` — multisite role with config-heavy `vars/main.yml`; exercises consumer-path rewrites.
3. `web-app-yourls`    — minimal app surface; baseline regression check.

Each app MUST be deployed standalone at least once, fully through the
`Role Loop` inspect-fix-redeploy cycle, until every Acceptance Criterion is
fulfilled and the deploy is clean. Restart the cycle from `web-app-nextcloud`
whenever a fix in one app could plausibly regress another.

## Commit Policy

- The agent MUST NOT create any git commit until **every** Acceptance Criterion
  in this document is checked off (`- [x]`).
- A single commit (or a tight, related sequence) lands the whole atomic refactor;
  no half-migrated intermediate commits.
- When all ACs are met, `make test` is green, and the three Final Iteration
  apps deploy cleanly, the agent instructs the operator to run `git-sign-push`
  outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT
  push.
