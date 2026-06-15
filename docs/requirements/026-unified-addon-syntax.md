# 026 - Unified Addon Syntax

## User Story

As a contributor to Infinito.Nexus, I want every role that ships application-level extensions to declare them through one unified `meta/addons.yml` contract, instead of today's per-app spelling (`addons`, `plugins`, `extensions`, `modules`, `mu_plugins`) scattered across `meta/services.yml`, `vars/main.yml`, and `tasks/`, so that addons are discoverable, lintable, and testable with a single schema, and so that any addon that bridges into another role declares that dependency explicitly through a service flag in `meta/services.yml`.

## Background

The repository already deploys role-level extension units, but each role spells the same concept differently and stores it in a different place:

- [web-app-friendica](../../roles/web-app-friendica/) calls them `addons` and inlines them under `friendica.addons` in [meta/services.yml](../../roles/web-app-friendica/meta/services.yml).
- [web-app-odoo](../../roles/web-app-odoo/) calls them `modules` (split `core` / `optional`) under `odoo.modules` in [meta/services.yml](../../roles/web-app-odoo/meta/services.yml).
- [web-app-nextcloud](../../roles/web-app-nextcloud/) calls them `plugins` and keeps one file per plugin under [vars/plugins/](../../roles/web-app-nextcloud/vars/plugins/).
- [web-app-wordpress](../../roles/web-app-wordpress/) calls them `plugins` (and separately `mu_plugins`) under [tasks/plugins/](../../roles/web-app-wordpress/tasks/plugins/).
- [web-app-mediawiki](../../roles/web-app-mediawiki/) calls them `extensions` and hard-codes the list in [vars/main.yml](../../roles/web-app-mediawiki/vars/main.yml).
- [web-app-xwiki](../../roles/web-app-xwiki/) calls them `plugins` (with nested `items[].id` + `version`) under `xwiki.plugins` in [meta/services.yml](../../roles/web-app-xwiki/meta/services.yml).
- [web-app-joomla](../../roles/web-app-joomla/) builds a single OIDC `plugin` in [tasks/07_oidc_plugin.yml](../../roles/web-app-joomla/tasks/07_oidc_plugin.yml).
- [desk-gnome-extensions](../../roles/desk-gnome-extensions/) calls them `plugins`/`extensions` and loops over `services.gnome-extensions.plugins`.

The [per-role meta layout](../contributing/design/role/services/layout.md) already lists `addons`, `plugins`, and `modules` among the keys *inlined* under the primary service entity. This requirement promotes that concept to a first-class, file-rooted `meta/addons.yml` topic, the same move requirement 011 made for `meta/info.yml` and requirement 008/009 made for other meta topics.

A recurring property of these extensions is that many of them exist **only to bridge into another role**: `ldapauth` and `user_ldap` bridge to `svc-db-openldap`; `sociallogin`, `oidc-authenticator`, `OpenIDConnect`, `plg_system_keycloak`, and the WordPress OIDC plugin bridge to the SSO provider (`web-app-keycloak`); `wp-discourse` bridges to `web-app-discourse`; XWiki's `matomo` plugin bridges to `web-app-matomo`. Today that bridge is implicit. This requirement makes it explicit: **an addon that bridges to another role MUST declare the bridged service, and that service MUST be present in the role's `meta/services.yml`.**

## Confirmed Decisions

These choices are settled at requirement creation time and bound the implementation. Re-opening any of them MUST be recorded in the implementing PR.

1. **One file, one topic.** Addon definitions live in `roles/<role>/meta/addons.yml`. The file-root convention applies: the file content IS the value of `applications.<role_id>.addons`, with no wrapping `addons:` key (see [layout.md](../contributing/design/role/services/layout.md)). The materialised path is `applications.<role_id>.addons.<addon_id>`, read via `lookup('config', application_id, 'addons.<addon_id>')`.
2. **Unified schema, native mechanism preserved.** Every addon entry uses one schema across all roles. The app-native term is retained only as the `mechanism` field (`addon`, `plugin`, `mu_plugin`, `extension`, `module`, `bridge`). Tasks keep using the upstream installer for that mechanism; only the *declaration* is unified. App-specific runtime configuration is carried under an opaque `config:` mapping that only the owning role's tasks interpret, so the surrounding schema stays uniform while each addon keeps its full per-addon payload. `meta/addons.yml` is therefore the single source for both the declaration and the runtime config: where a role previously split the enable/disable declaration from a per-addon config payload (e.g. Nextcloud's [vars/plugins/](../../roles/web-app-nextcloud/vars/plugins/)), both move into `meta/addons.yml` and the superseded per-addon config files are deleted by the migration.
3. **Bridges are explicit and validated.** When an addon itself integrates with another role, it MUST list the bridged service key under `bridges:`. Each listed key MUST resolve to a service block already declared in the same role's `meta/services.yml`. Lint fails otherwise. Front-door auth gates such as oauth2-proxy are not addon bridges unless the addon itself talks to that service. **Two distinct meanings of "bridge" exist and MUST NOT be conflated:** the `bridges:` *field* names an in-repo cross-role service dependency (e.g. an addon that talks to `svc-db-openldap`), whereas `mechanism: bridge` marks an addon that *is* a network/appservice bridge to an external system (e.g. a Matrix mautrix bridge to WhatsApp/Telegram). A single addon MAY be both: a `mechanism: bridge` addon MAY also declare a `bridges:` dependency on an in-repo service it relies on.
4. **No new secret store.** Any credential an addon needs continues to be declared in [`meta/schema.yml`](../contributing/design/role/services/layout.md) `credentials:` and read via `lookup('config', application_id, 'credentials.<name>')`.
5. **Enable state defaults to off; deliberately-wired integrations auto-enable with their partner.** `enabled` is optional and defaults to `false` unless `required: true` is set. An addon that bridges a service MUST derive its effective enablement from that service's `enabled` flag (never a duplicated group-membership expression), so a deliberately-wired cross-role integration activates automatically whenever its partner role is co-deployed (`services.<target>.enabled` is true) and stays off otherwise. Any credential an addon needs is declared in `meta/schema.yml` `credentials:` and read via `lookup('config', application_id, 'credentials.<name>')` (Decision 4) — auto-generated where possible, or supplied through the same credentials mechanism's manual-entry path where the operator must enter the secret. There is no separate opt-in exception: auto-enable-with-partner holds, and an operator-entered credential resolves through `credentials` like any other. This auto-enable-with-partner rule is distinct from update-automation-discovered addons (Decision 10), which are added hard-off.
6. **Required addons are explicit, and install failure is gated by `required`.** Every addon carries a boolean `required` field (default `false`). Core components that are part of the deployed app contract, such as Odoo's core modules, use `required: true`: they are always installed, MAY omit `enabled`, and MUST NOT set `enabled: false`. The field also governs install-failure behaviour: when an addon's installation fails, a `required: true` addon MUST hard-fail the play (the deploy stops), while a `required: false` addon MUST only emit a warning, skip that addon, and let the play continue.
7. **Workload-neutral contract.** `meta/addons.yml` applies to any role type that declares role-level extensions, including desktop roles such as `desk-gnome-extensions`. The materialised path still uses the role's assembled application entry, `applications.<role_id>.addons`.
8. **First slice.** The first end-to-end migration is `web-app-friendica` (`ldapauth`, bridges `ldap` to `svc-db-openldap`), because it already exercises the bridge rule and the service-flag enablement path.
9. **External drift monitoring.** Addon freshness is checked by opt-in external tests under `tests/external/update/addons/`. These tests are warn-only, emit GitHub Actions warning annotations, and are excluded from `make test` in the same way as Docker image and repository-ref external update checks.
10. **Update PR behaviour.** The scheduled update workflow MAY open or refresh an update pull request for addon version bumps and newly discovered catalog entries. Addon entries *discovered by update automation* MUST be added disabled by default (`enabled: false`) and MUST NOT silently enable new runtime behaviour. This hard-off default applies to auto-discovered addons only; it does NOT override the auto-enable-with-partner rule for deliberately-wired integrations (Decision 5).
11. **Every addon ships a Playwright test.** Each addon with a user-facing surface MUST add a matching Playwright spec under `roles/<role>/files/playwright/` that exercises that addon's behaviour (e.g. an `ldapauth`/`sociallogin` login path, a `wp-discourse` round-trip, an enabled Odoo module's UI entry point). An addon with no web-facing surface (e.g. a `desk-gnome-extensions` desktop extension) is exempt and MUST carry a one-line note in the role README stating why. No addon is considered implemented or migrated until its Playwright test is present and green, or its exemption is documented. Cross-role integration specs (proving two roles are actually connected) run under a dedicated **integration-pair deploy variant** that co-deploys both partner roles, and are added incrementally as each ✅ pair is wired rather than all upfront.
12. **Addon state is a variant axis.** Optional addons (`required: false`) MUST express their enabled/disabled split through the role's [`meta/variants.yml`](../contributing/design/role/services/layout.md) so CI matrix runs exercise both states, mirroring requirement 025's MCP variant axis. Required addons (`required: true`) are not a variant axis because they are always installed.
13. **Network bridges are addons.** Appservice / network bridges (e.g. the Matrix `mautrix` bridges to WhatsApp, Telegram, Signal, Slack, Facebook, Instagram) are addons declared in `meta/addons.yml` with `mechanism: bridge`, one entry per bridged network. Each bridge owns its credentials in [`meta/schema.yml`](../contributing/design/role/services/layout.md) and is `required: false` and disabled by default. The role's former bridge declarations (e.g. `web-app-matrix`'s [vars/bridges.yml](../../roles/web-app-matrix/vars/bridges.yml)) are absorbed into `meta/addons.yml`.
14. **The integration matrix is the cross-role addon backlog.** The full role×role capability map lives in the generated companion [027-integration-matrix.md](027-integration-matrix.md) (source of truth: [027-integration-matrix.gen.py](027-integration-matrix.gen.py)). ☑️ cells are integrations **already wired** through an infinito-native service flag in the row role's `meta/services.yml` (e.g. `sso`→keycloak, `matomo`, `prometheus`, `email`→mailu) — derived by scanning the repo, no action required. ✅ cells are verified **upstream app↔app plugins not yet declared** as addons — this is the backlog this requirement commits to wire. 🪙 cells are the same as ✅ but gated behind a commercial tier (opt-in, operator-enabled). ❌ cells have no known integration. The matrix MUST be regenerated (not hand-edited) whenever a role or an integration is added; the `meta/addons.yml` migrations turn ✅ into ☑️ over time.
15. **Scope is the full backlog, executed in phases.** The definition of done is the FULL set: every ✅ cell in the matrix wired as an addon, and an exhaustive per-`web-app-*`-role upstream-plugin survey completed so the ✅ layer is exhaustive rather than hub-biased. Delivery is phased — the shared contract + the first-slice roles land first (see [Implementation Strategy](#implementation-strategy)), then the remaining roles and ✅ wirings sweep incrementally — but no phase reduces scope: the requirement is not complete until the full ✅ set is wired and every `web-app-*` role surveyed.
16. **The integration matrix is a generated artifact with a sanctioned generator.** `027-integration-matrix.gen.py` stays under `docs/requirements/` but MUST be refactored to satisfy the repo lints: its `EDGES` data moves into a sibling data module so the entrypoint stays under the 500-line limit, it uses the shared project-root helper instead of a local `__file__` upward walk, and it carries no self-path literal or `requirement NNN` token. The generated `027-integration-matrix.md` carries a `generated-artifact / not-a-requirement` head marker so the requirements-completeness/archival lint skips it. Dead upstream URLs in `EDGES` are fixed or dropped on regeneration.
17. **Only bridging addons add a service block.** A `<target>:` service block is added to the row role ONLY for addons that declare a `bridges:` dependency (per Decision 3) — i.e. the in-repo cross-role integrations; a plain addon with no cross-role dependency adds no service block. Each bridging addon's `<target>:` block carries the standard dynamic `enabled`/`shared` flags with matching true/false `meta/variants.yml` coverage, and — for web-facing pairs — a co-deploy Playwright spec. Across the in-repo ✅ set this is a bounded, mechanical expansion scoped to the bridging integrations, accepted as part of Decision 15's full scope.
18. **Numbering.** This document is `026-unified-addon-syntax.md`, forming the trio `025-mcp-role-integration` → `026-unified-addon-syntax` → `027-integration-matrix`. The pre-existing `025-mcp-role-integration` vs `025-web-app-matrix-ansible-flavor` number collision is out of this requirement's scope; a separate doc owns its resolution.

## Current State Audit

Each row is a migration target. The "Bridges" column is the cross-role dependency this requirement makes explicit. "Today's location" is where the declaration lives before migration.

| Role | App-native term (`mechanism`) | Addon ids today | Bridges (service → role) | Today's location |
|---|---|---|---|---|
| [web-app-friendica](../../roles/web-app-friendica/) | `addon` | `ldapauth` | `ldap` → `svc-db-openldap` | [meta/services.yml](../../roles/web-app-friendica/meta/services.yml) `friendica.addons` |
| [web-app-odoo](../../roles/web-app-odoo/) | `module` | `crm, contacts, sale_management, account, website, project, stock` (core); `[]` (optional) | none today | [meta/services.yml](../../roles/web-app-odoo/meta/services.yml) `odoo.modules` |
| [web-app-nextcloud](../../roles/web-app-nextcloud/) | `plugin` | `bbb, onlyoffice, richdocuments, sociallogin, spreed, user_ldap, whiteboard, xwiki` | `sociallogin` → `web-app-keycloak`, `user_ldap` → `svc-db-openldap` | [vars/plugins/](../../roles/web-app-nextcloud/vars/plugins/) |
| [web-app-wordpress](../../roles/web-app-wordpress/) | `plugin`, `mu_plugin` | `daggerhart-openid-connect-generic, wp-discourse` (+ mu-plugins) | OIDC → `web-app-keycloak`, `wp-discourse` → `web-app-discourse` | [tasks/plugins/](../../roles/web-app-wordpress/tasks/plugins/) |
| [web-app-mediawiki](../../roles/web-app-mediawiki/) | `extension` | `PluggableAuth, OpenIDConnect` | `OpenIDConnect` → `web-app-keycloak` | [vars/main.yml](../../roles/web-app-mediawiki/vars/main.yml) |
| [web-app-xwiki](../../roles/web-app-xwiki/) | `plugin` | `oidc-authenticator, ldap-authenticator, matomo` | `oidc` → `web-app-keycloak`, `ldap` → `svc-db-openldap`, `matomo` → `web-app-matomo` | [meta/services.yml](../../roles/web-app-xwiki/meta/services.yml) `xwiki.plugins` |
| [web-app-joomla](../../roles/web-app-joomla/) | `plugin` | `plg_system_keycloak` | `sso` → `web-app-keycloak` | [tasks/07_oidc_plugin.yml](../../roles/web-app-joomla/tasks/07_oidc_plugin.yml) |
| [web-app-matrix](../../roles/web-app-matrix/) | `bridge` | `mautrix-whatsapp, mautrix-telegram, mautrix-signal, mautrix-slack, mautrix-facebook, mautrix-instagram` | external networks (no in-repo service); each owns a DB credential | [vars/bridges.yml](../../roles/web-app-matrix/vars/bridges.yml) |
| [web-app-discourse](../../roles/web-app-discourse/) | `plugin` | `docker_manager, discourse-activity-pub, discourse-akismet, discourse-ldap-auth` | `discourse-ldap-auth` → `svc-db-openldap` | [meta/services.yml](../../roles/web-app-discourse/meta/services.yml) `discourse.plugins` |
| [web-app-pretix](../../roles/web-app-pretix/) | `plugin` | `oidc` (v2.3.1) | `sso` → `web-app-keycloak` | [meta/services.yml](../../roles/web-app-pretix/meta/services.yml) `pretix.plugins` |
| [web-app-mattermost](../../roles/web-app-mattermost/) | `plugin` | volume-managed plugins (`plugins`, `client-plugins`) | none declared today | [vars/main.yml](../../roles/web-app-mattermost/vars/main.yml), [meta/volumes.yml](../../roles/web-app-mattermost/meta/volumes.yml) |
| [desk-chromium](../../roles/desk-chromium/) | `extension` | CRX ids, `force_installed` (e.g. uBlock Origin) | none (desktop role) | [meta/services.yml](../../roles/desk-chromium/meta/services.yml) `plugins` |
| [desk-firefox](../../roles/desk-firefox/) | `extension` | XPI urls (uBlock Origin, KeePassXC) | none (desktop role) | [meta/services.yml](../../roles/desk-firefox/meta/services.yml) `plugins` |
| [desk-gnome](../../roles/desk-gnome/) | `extension` | gnome-shell extensions (enable/disable tuples) | none (desktop role) | [meta/services.yml](../../roles/desk-gnome/meta/services.yml) `plugins` |
| [desk-gnome-extensions](../../roles/desk-gnome-extensions/) | `extension` | configured list (`services.gnome-extensions.plugins`) | none (desktop role) | [meta/services.yml](../../roles/desk-gnome-extensions/meta/services.yml) |

### Out of scope: database/runtime engine extensions

Two roles declare an `extensions:` key that is **not** an application addon but a database/cache engine feature, provisioned at the storage layer. These MUST stay where they are and MUST NOT move into `meta/addons.yml`:

- [web-app-mobilizon](../../roles/web-app-mobilizon/) — PostgreSQL extensions `postgis, pg_trgm, unaccent` ([meta/services.yml](../../roles/web-app-mobilizon/meta/services.yml)).
- [web-app-bookwyrm](../../roles/web-app-bookwyrm/) — engine extension `bloom` ([meta/services.yml](../../roles/web-app-bookwyrm/meta/services.yml)).

The audit MUST classify these as `db-extension` (out of scope), so a later sweep does not mistake them for app addons. If a future role mixes app addons and DB extensions under one key, the migration MUST split them by destination.

A grep for `meta/addons.yml` before implementation MUST return nothing, and that baseline MUST be recorded in the implementing PR.

## Cross-Role Integration Matrix

The companion [027-integration-matrix.md](027-integration-matrix.md) is a generated role×role matrix over the entity names of every `web-app-*` and `web-svc-*` role. Each cell marks whether the **row** role wires in the **column** role:

- ☑️ — already wired via an infinito-native service flag in the row role's `meta/services.yml` (cell links to that declaration);
- ✅ — a verified upstream app↔app plugin exists but is not yet declared as an addon (cell links to the plugin page) — the backlog;
- 🪙 — same as ✅ but gated behind a commercial / paid tier;
- ❌ — no known integration;
- — — diagonal (same role).

The matrix is **directional** (the row hosts the plugin/flag); bidirectional pairs such as `nextcloud`↔`openproject` carry a symbol in both cells. It is generated by [027-integration-matrix.gen.py](027-integration-matrix.gen.py): ☑️ edges are scanned from every role's `meta/services.yml` (the `sso`/`matomo`/`prometheus`/`email`/`dashboard`/`css`/`logout`/`cdn`/`coturn`/`collabora`/`onlyoffice`/`libretranslate` keys), and ✅/🪙 edges come from a curated, web-verified `EDGES` map. It MUST be regenerated rather than hand-edited. At creation time it covers 82 roles with **511 infinito-native (☑️) wired edges plus 96 curated upstream (✅/🪙) edges**. The ☑️ layer is exhaustive (it is scanned from the repo); the ✅/🪙 layer is **not yet exhaustive** — it grows as each role's upstream plugin ecosystem is researched in depth (e.g. a MediaWiki deep-dive added `DiscourseSsoConsumer`, `PeerTubeEmbed`, `MachineTranslation`→libretranslate, `Extension:AWS`→minio, and an LLM editor→openwebui). The ✅/🪙 set is the **backlog**: every ✅ pair is an addon this requirement commits to declare and wire (see Acceptance Criteria), and completing the per-role upstream survey is itself an acceptance criterion.

## Target Schema

### Addon declaration: `meta/addons.yml`

Every role that ships role-level extensions MUST declare them in `roles/<role>/meta/addons.yml`. The file root IS the addons map keyed by `<addon_id>`. There is NO wrapping `addons:` key.

```yaml
# roles/web-app-friendica/meta/addons.yml  (file root IS the addons map)
ldapauth:
  enabled: "{{ lookup('config', application_id, 'services.ldap.enabled') | bool }}"
  required: false             # true for core modules that must always install
  mechanism: addon            # addon | plugin | mu_plugin | extension | module
  source: upstream            # upstream | bundled | vendored | built
  bridges:                    # optional; service keys declared in meta/services.yml
    - ldap
  version: ""                 # optional upstream pin; "" means upstream default
  group: optional             # optional grouping label (e.g. odoo core/optional)
  update:
    monitored: true           # optional; external tests check latest versions
    catalog: friendica-addons # optional; supported upstream catalog adapter
    upstream_id: ldapauth     # optional; defaults to addon id
```

Field rules:

- `enabled` (optional) defaults to `false` when omitted, except when `required: true` is set. When the addon bridges exactly one service, `enabled` SHOULD reference that service's `enabled` flag rather than re-deriving group membership.
- `required` (optional) defaults to `false`. When `required: true`, the addon is part of the role's baseline install contract, is treated as enabled even when `enabled` is omitted, and MUST NOT set `enabled: false`. `required` also gates install-failure handling: a failed install of a `required: true` addon MUST hard-fail the play; a failed install of a `required: false` addon MUST emit a warning, skip the addon, and continue.
- `mechanism` (required) MUST be one of `addon`, `plugin`, `mu_plugin`, `extension`, `module`, `bridge`. It records the upstream installation mechanism and selects which task path installs the addon. `mechanism: bridge` denotes a network/appservice bridge addon (see Confirmed Decision 13) and is distinct from the `bridges:` field below.
- `source` (required) MUST be one of `upstream` (installed from the app's own registry), `bundled` (ships with the image), `vendored` (committed under `roles/<role>/files/`), or `built` (compiled/zipped during the play, e.g. the Joomla OIDC plugin).
- `bridges` (optional) MUST be a non-empty list when present. Each entry MUST name a service key that exists in the same role's `meta/services.yml`. Omit the key entirely when the addon has no cross-role dependency.
- `version` (optional) MUST be a string. `""` means "track the app's default". A concrete pin MUST be a string, never an unquoted number.
- `group` (optional) is a free label used by roles that partition addons (e.g. Odoo `core` vs `optional`). It MUST NOT affect enablement.
- `update` (optional) controls live upstream monitoring. `update.monitored` defaults to `false`; `update.catalog` MUST name a supported external-test catalog adapter; `update.upstream_id` defaults to `<addon_id>`.
- `config` (optional) is an opaque, role-interpreted mapping holding the addon's full runtime configuration payload (e.g. Nextcloud `occ config:app` key/value sets, OIDC provider blocks). Lint MUST NOT constrain its inner shape beyond requiring a mapping; only the owning role's tasks read it. Secrets inside `config` MUST resolve through `lookup('config', application_id, 'credentials.<name>')` and MUST NOT be inlined literally. Lint enforces this with a bounded heuristic: any `config` value whose key matches a secret-name pattern (`*secret*`, `*password*`, `*token*`, `*client_secret*`, `*api_key*`, case-insensitive) MUST be a `lookup(..., 'credentials.<name>')` expression; a bare literal under such a key fails lint.

#### Worked example: absorbing per-addon config

A Nextcloud plugin that previously lived as a standalone config file moves wholesale into its `config:` block:

```yaml
# roles/web-app-nextcloud/meta/addons.yml  (excerpt)
sociallogin:
  enabled: "{{ lookup('config', application_id, 'services.sso.enabled') | bool }}"
  mechanism: plugin
  source: upstream
  bridges:
    - sso
  config:
    plugin_configuration:
      - appid: sociallogin
        configkey: custom_providers
        configvalue:
          custom_oidc:
            - name: "{{ lookup('domain','web-app-keycloak') }}"
              clientId: "{{ OIDC.CLIENT.ID }}"
              clientSecret: "{{ OIDC.CLIENT.SECRET }}"
              # ... remaining provider keys, verbatim from the former vars/plugins/sociallogin.yml ...
```

The former [roles/web-app-nextcloud/vars/plugins/sociallogin.yml](../../roles/web-app-nextcloud/vars/plugins/sociallogin.yml) is deleted; the install/enable/configure tasks read `applications.web-app-nextcloud.addons.sociallogin.config` instead.

#### Worked example: network bridge addon

A Matrix mautrix bridge becomes one addon entry per bridged network, absorbing the former [vars/bridges.yml](../../roles/web-app-matrix/vars/bridges.yml):

```yaml
# roles/web-app-matrix/meta/addons.yml  (excerpt)
mautrix-telegram:
  enabled: false
  required: false
  mechanism: bridge
  source: upstream
  config:
    bridge_name: telegram
    database_username: mautrix_telegram_bridge
    database_name: mautrix_telegram_bridge
    database_password: "{{ lookup('config', application_id, 'credentials.mautrix_telegram_bridge_database_password') }}"
```

The bridge's database password stays declared in [meta/schema.yml](../../roles/web-app-matrix/meta/schema.yml) `credentials:` and is referenced, never inlined. Each additional network (`whatsapp`, `signal`, `slack`, `facebook`, `instagram`) is its own `mechanism: bridge` addon.

### Install-failure handling

The install task path for every addon MUST honour the `required` field:

- A `required: true` addon whose install step fails MUST fail the play (no `failed_when: false` swallowing the error).
- A `required: false` addon whose install step fails MUST register the failure, emit a warning (role log line plus, in CI, a GitHub Actions warning annotation via `utils.annotations.message.warning`), skip the addon's remaining steps, and let the play continue.
- The warning MUST name the role, the addon id, and the failing step so the operator can act without reading raw task output.

### Bridge rule

The central rule of this requirement:

> For every addon entry with a non-empty `bridges:` list, each listed service key MUST be declared as a service block in the same role's `meta/services.yml`, following the established cross-role flag pattern.

Example: the `ldapauth` addon above requires that [web-app-friendica/meta/services.yml](../../roles/web-app-friendica/meta/services.yml) already declares:

```yaml
# roles/web-app-friendica/meta/services.yml  (excerpt)
ldap:
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
```

Rules:

- An addon MUST NOT bridge a service that is absent from `meta/services.yml`; lint fails with the missing key named.
- A bridged service block MUST carry the standard `enabled` / `shared` flags so requirement 019 (services.yml parity) and the SSO/LDAP coverage requirements (017, 018) continue to apply unchanged.
- The bridge declaration is one-directional metadata (this role depends on that service). It MUST NOT be used to auto-enable the other role; enablement stays driven by group membership and the existing `run_after` ordering.
- If a role uses another service around the application but the addon does not talk to that service directly, the service MUST stay in `meta/services.yml` and MUST NOT be listed in the addon's `bridges:`. Friendica's oauth2-proxy-backed `sso` service is such a front-door auth gate for `ldapauth`.

### Materialised path and loader

- `meta/addons.yml.<addon_id>.<...>` materialises at `applications.<role_id>.addons.<addon_id>.<...>`, consistent with the file-root convention in [layout.md](../contributing/design/role/services/layout.md).
- The existing application loader (`utils/cache/applications.py`) MUST load `meta/addons.yml` like the other file-rooted meta topics. No new generated repository-wide dictionary is introduced.
- The `addons` key MUST be removed from the "inlined under the primary entity" set in [layout.md](../contributing/design/role/services/layout.md) and documented as its own topic file.

### External update monitoring

Addon monitoring MUST follow the existing external-update pattern used for Docker image versions and repository refs.

Rules:

- Live upstream checks MUST live under `tests/external/update/addons/` and run through `make test-external`, not through the default `make test` flow.
- The external addon test MUST emit warnings, not failures, when a monitored addon has a newer upstream version.
- The external addon test MUST emit warnings, not failures, when a supported catalog adapter detects a new relevant addon that is not listed in `meta/addons.yml`.
- Catalog discovery MUST be bounded by explicit adapters and curated relevance rules. The test MUST NOT warn for every package in broad public marketplaces such as the full WordPress plugin directory.
- New addon suggestions MUST include enough data for review: role id, addon id, upstream id, mechanism, source, catalog URL, and why the addon is considered relevant.
- Version suggestions MUST include the current pinned version, latest upstream version, source file, and line number where possible.
- The scheduled update workflow MUST be able to reuse the same discovery logic in update mode. Version bumps MAY update `version`; new addon entries MAY be added with `enabled: false`, `required: false`, and complete `update` metadata.
- Update automation MUST preserve existing `enabled`, `required`, `bridges`, and credential-related fields, and MUST NOT enable newly discovered addons automatically.

## Acceptance Criteria

### Repository-wide audit

- [ ] A deterministic audit command or test enumerates every role under `roles/` and classifies addon support by `mechanism` (`addon`, `plugin`, `mu_plugin`, `extension`, `module`, `bridge`), `db-extension` (out of scope), or `none`.
- [ ] The audit reproduces every row of the [Current State Audit](#current-state-audit) — including the `bridge`-mechanism (`web-app-matrix`), the newly surveyed `plugin`/`extension` roles (`web-app-discourse`, `web-app-pretix`, `web-app-mattermost`, `desk-chromium`, `desk-firefox`, `desk-gnome`), and the out-of-scope `db-extension` roles (`web-app-mobilizon`, `web-app-bookwyrm`) — and records, per role, the addon ids, their `mechanism`, their `required` state, and their `bridges`.
- [ ] A grep for `meta/addons.yml` before implementation is recorded in the implementing PR to show the baseline was empty.

### Shared contract

- [ ] [layout.md](../contributing/design/role/services/layout.md) documents `meta/addons.yml`: file-root convention, the addon schema, field defaults, allowed values, and the materialised path; and removes `addons` from the inlined-key list.
- [ ] The application loader reads `meta/addons.yml` for every role and exposes `applications.<role_id>.addons.<addon_id>` through `lookup('config', application_id, 'addons.<addon_id>')`.
- [ ] Role-meta lint under [`tests/lint/ansible/services/`](../../tests/lint/ansible/services/) rejects an invalid `mechanism` (outside the `addon`/`plugin`/`mu_plugin`/`extension`/`module`/`bridge` set), an invalid `source`, an invalid `update.catalog`, an empty `bridges: []`, a non-string `version`, a non-boolean `required`, `required: true` combined with `enabled: false`, a non-mapping `config`, a literal secret inlined in `config`, and missing required fields, honouring the `# nocheck:` suppression convention.
- [ ] After the Nextcloud migration, no `roles/web-app-nextcloud/vars/plugins/*.yml` plugin-config file remains; a test asserts the directory's former per-plugin payloads now live under `applications.web-app-nextcloud.addons.<id>.config`.

### Bridge contract

- [ ] Lint fails when an addon's `bridges:` entry names a service key absent from the same role's `meta/services.yml`, and the error message names the role, addon id, and missing service key.
- [ ] Lint verifies that every bridged service block carries `enabled` and `shared` flags.
- [ ] A bridged addon's `enabled` value referencing its single bridged service's `enabled` flag passes lint without a duplicated group-membership expression.
- [ ] Lint allows role-level service dependencies that are not addon bridges, such as Friendica's `sso` front-door auth gate, to remain in `meta/services.yml` without appearing under an unrelated addon's `bridges:`.

### Per-role migration

- [ ] [web-app-friendica](../../roles/web-app-friendica/) declares `ldapauth` in `meta/addons.yml` with `bridges: [ldap]`; the `ldap` and `sso` service blocks remain in `meta/services.yml`; [tasks/04_addons.yml](../../roles/web-app-friendica/tasks/04_addons.yml) reads the addon list from the new path; deploy behaviour is unchanged.
- [ ] [web-app-odoo](../../roles/web-app-odoo/) declares its `core` and `optional` modules in `meta/addons.yml` using `mechanism: module`, `required: true` for core modules, and the `group` label; the install path reads the new path.
- [ ] [web-app-nextcloud](../../roles/web-app-nextcloud/) declares each plugin in `meta/addons.yml`; `sociallogin` bridges `sso` and `user_ldap` bridges `ldap`, both present in `meta/services.yml`; each plugin's full runtime config from [vars/plugins/](../../roles/web-app-nextcloud/vars/plugins/) is absorbed into its addon `config:` block and the superseded `vars/plugins/*.yml` files are deleted; the install/enable/configure tasks read the addon `config:` payload; deploy behaviour is unchanged.
- [ ] [web-app-wordpress](../../roles/web-app-wordpress/) declares its `plugin` and `mu_plugin` entries in `meta/addons.yml`; the OIDC plugin bridges `sso` and `wp-discourse` bridges the Discourse service.
- [ ] [web-app-mediawiki](../../roles/web-app-mediawiki/) declares `PluggableAuth` and `OpenIDConnect` in `meta/addons.yml` with `mechanism: extension`; `OpenIDConnect` bridges `sso`.
- [ ] [web-app-xwiki](../../roles/web-app-xwiki/) declares its three plugins in `meta/addons.yml`, preserving `version` pins; bridges `sso`, `ldap`, and `matomo` resolve to service blocks.
- [ ] [web-app-joomla](../../roles/web-app-joomla/) declares `plg_system_keycloak` in `meta/addons.yml` with `mechanism: plugin`, `source: built`, and `bridges: [sso]`.
- [ ] [web-app-matrix](../../roles/web-app-matrix/) declares each mautrix network bridge in `meta/addons.yml` with `mechanism: bridge`, `required: false`, `enabled: false` by default, and its DB credential referenced from `meta/schema.yml`; [vars/bridges.yml](../../roles/web-app-matrix/vars/bridges.yml) is absorbed and deleted.
- [ ] [web-app-discourse](../../roles/web-app-discourse/) declares its plugins in `meta/addons.yml` with `mechanism: plugin`; `discourse-ldap-auth` carries `bridges: [ldap]` resolving to the `ldap` service block, while `docker_manager`, `discourse-activity-pub`, and `discourse-akismet` carry no `bridges`.
- [ ] [web-app-pretix](../../roles/web-app-pretix/) declares its `oidc` plugin in `meta/addons.yml` with `mechanism: plugin`, the `2.3.1` pin preserved as a string `version`, and `bridges: [sso]`.
- [ ] [web-app-mattermost](../../roles/web-app-mattermost/) declares its plugins in `meta/addons.yml` with `mechanism: plugin`; the plugin volumes remain in `meta/volumes.yml`.
- [ ] [desk-chromium](../../roles/desk-chromium/) and [desk-firefox](../../roles/desk-firefox/) declare their browser extensions in `meta/addons.yml` with `mechanism: extension`, no `bridges`, and a documented Playwright exemption (no in-app web surface to drive).
- [ ] [desk-gnome](../../roles/desk-gnome/) declares its gnome-shell extensions in `meta/addons.yml` with `mechanism: extension` and no `bridges`.
- [ ] [desk-gnome-extensions](../../roles/desk-gnome-extensions/) declares its extensions in `meta/addons.yml` with `mechanism: extension` and no `bridges`.
- [ ] [web-app-mobilizon](../../roles/web-app-mobilizon/) and [web-app-bookwyrm](../../roles/web-app-bookwyrm/) keep their `extensions:` (PostgreSQL/engine extensions) in `meta/services.yml`; they are classified `db-extension` and explicitly NOT migrated to `meta/addons.yml`.

### Cross-role integration (matrix backlog)

- [ ] [027-integration-matrix.md](027-integration-matrix.md) is regenerated from [027-integration-matrix.gen.py](027-integration-matrix.gen.py) and committed; a check fails if the committed matrix differs from a fresh generation (no hand edits). The generator derives ☑️ edges by scanning every role's `meta/services.yml` integration keys and renders ✅/🪙 from the curated `EDGES` map.
- [ ] The matrix axes contain the entity name of **every** `web-app-*` and `web-svc-*` role; a role added later forces a matrix regeneration.
- [ ] ☑️ cells (infinito-native service flags already declared in `meta/services.yml`) are NOT re-declared as `meta/addons.yml` addons — they remain service integrations; only ✅/🪙 cells become new addons.
- [ ] A per-role upstream-plugin survey is completed for **every** `web-app-*` role, not only the integration hubs, so the ✅/🪙 layer is exhaustive rather than hub-biased. Each survey records, per partner role, the real upstream plugin (or its documented absence) with a source URL; the MediaWiki survey (which surfaced `DiscourseSsoConsumer`, `PeerTubeEmbed`, `MachineTranslation`→libretranslate, `Extension:AWS`→minio, an LLM editor→openwebui) is the template for depth.
- [ ] **Every ✅ cell is wired**: for each ✅ pair (row → column), the row role declares an addon in its `meta/addons.yml` that integrates the column role, with `mechanism` set appropriately and — when the column role is an in-repo role — a `bridges:` entry resolving to the row role's `meta/services.yml` service for that target.
- [ ] Each wired integration addon is `required: false` and disabled by default, and its enablement is gated on the target role being present (the relevant `services.<target>.enabled` flag), so an integration never activates when its partner role is not deployed.
- [ ] **🪙 (commercial) cells are opt-in**: they are declared in `meta/addons.yml` but remain disabled, and the role README documents the required commercial tier; they are NOT enabled by default and do not block the requirement.
- [ ] Where the cell links to an already-wired plugin (e.g. Nextcloud↔Collabora/BBB, WordPress↔Discourse), the migration reconciles the existing wiring with the matrix entry instead of duplicating it.
- [ ] Each newly wired ✅ integration with a user-facing surface ships a Playwright spec (per Confirmed Decision 11) proving the two roles are actually connected when both are deployed.
- [ ] SSO-to-`keycloak` cells already satisfied centrally by the `sso` service (requirement 021) are marked as such and are NOT re-implemented as duplicate per-role OIDC addons.

### External drift and update PRs

- [ ] `tests/external/update/addons/` contains a warn-only external test that checks every addon with `update.monitored=true` for newer upstream versions.
- [ ] The external addon test emits GitHub Actions warning annotations for outdated addon versions and for relevant new catalog entries that are not listed in `meta/addons.yml`.
- [ ] The external addon test is runnable through `make test-external` and is intentionally excluded from the default `make test` flow.
- [ ] The supported catalog adapters are documented and bounded so broad marketplaces do not produce unreviewable warning noise.
- [ ] The scheduled update workflow opens or refreshes an update pull request when addon versions can be bumped or when relevant new addon entries can be added.
- [ ] Update automation adds newly discovered addons with `enabled: false`, `required: false`, complete `update` metadata, and no credentials.
- [ ] Update automation preserves existing enablement, bridge, required, and credential-related fields when bumping addon versions.

### Tests

- [ ] Unit or integration tests validate the addon schema and reject unsafe or malformed entries.
- [ ] A parity test (in the spirit of requirement 019) asserts that every addon `bridges:` key has a matching `meta/services.yml` block, repo-wide.
- [ ] A schema test verifies that `enabled` may be omitted, defaults to `false` for optional addons, defaults to true for `required: true`, and rejects `required: true` with `enabled: false`.
- [ ] An install-failure test proves that a failing `required: true` addon hard-fails the play, while a failing `required: false` addon emits a warning, is skipped, and the play continues.
- [ ] Each role with optional (`required: false`) addons expresses the enabled/disabled split as a `meta/variants.yml` axis so the CI matrix exercises both states (mirroring requirement 025).
- [ ] Unit tests cover the external addon discovery logic with fixture catalogs for a version bump, a newly discovered addon, and a marketplace entry intentionally ignored by the curated relevance rules.
- [ ] Each migrated role's existing deploy path stays green; no addon behaviour regresses.
- [ ] LDAP- and SSO-bridging addons remain covered by the existing Playwright LDAP/SSO requirements (017/018) without new per-role wiring.
- [ ] Every addon with a user-facing surface ships a matching Playwright spec under `roles/<role>/files/playwright/` covering that addon's behaviour, and that spec is green before the addon is marked migrated; web-surface-less addons carry a documented README exemption instead.

### Documentation

- [ ] [layout.md](../contributing/design/role/services/layout.md) and the [plugins README](../../plugins/README.md) cross-reference each other so the Ansible-`plugins/` concept and the application-`addons` concept are not conflated.
- [ ] Each migrated role README documents its addons, their `mechanism`, default state, and which services they bridge.
- [ ] This requirement file is cross-linked from the implementing PR.

## Validation Apps

The implementation MUST validate the bridge rule and the loader on the first slice before sweeping the rest:

```bash
INFINITO_APPS="web-app-friendica" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

After the first slice is green, each migrated role MUST pass its role-local deploy path and any matrix variants affected by the migration.

## Prerequisites

Before starting implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

1. Add the `meta/addons.yml` schema and loader support, the `tests/lint/ansible/services/` lint rules (schema + bridge resolution), and the [layout.md](../contributing/design/role/services/layout.md) documentation.
2. Add the repo-wide bridge-parity test.
3. Add the external addon update checker, its fixture-backed unit tests, and update-workflow integration for warn-only drift detection and update pull requests.
4. Migrate `web-app-friendica` as the first end-to-end slice (addon list + bridge resolution + task rewire) and prove deploy parity.
5. Sweep the remaining roles one at a time: odoo, nextcloud, wordpress, mediawiki, xwiki, joomla, matrix (bridges), discourse, pretix, mattermost, desk-chromium, desk-firefox, desk-gnome, and desk-gnome-extensions. Keep each role's README, variants, and tests aligned. Leave the out-of-scope `db-extension` roles (mobilizon, bookwyrm) untouched.
6. Remove `addons` from the inlined-key set once every role is migrated.

## Commit Policy

- The shared schema, loader, lint, and the first migrated role MAY land together.
- Each additional role SHOULD land in a focused commit or PR when it can be validated independently.
- The implementing PR MUST NOT mark any Acceptance Criterion complete until the behavior is verified end to end.
