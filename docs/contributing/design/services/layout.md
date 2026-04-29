# Per-Role Meta Layout 🗂️

This page is the SPOT for the on-disk shape of every role's metadata after
[req-008](../../../requirements/008-role-meta-layout.md),
[req-009](../../../requirements/009-per-role-networks-and-ports.md),
[req-010](../../../requirements/010-role-meta-runafter-lifecycle-migration.md), and
[req-011](../../../requirements/011-role-meta-info-migration.md).

The legacy entry files `roles/<role>/config/main.yml`,
`roles/<role>/users/main.yml`, and `roles/<role>/schema/main.yml` are gone.
All role-owned metadata lives under `roles/<role>/meta/<topic>.yml`.

## File Layout 📁

| File                     | Contents                                                                                                                                          |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `meta/main.yml`          | Ansible Galaxy metadata + Ansible `dependencies:`. **No** project-internal `run_after:` / `lifecycle:` keys (req-010), **no** `logo:` / `homepage:` / `video:` / `display:` (req-011). |
| `meta/services.yml`      | Per-entity service config. **File root IS the services map** keyed by `<entity_name>`. No `compose:` and no `services:` wrapper.                  |
| `meta/server.yml`        | CSP, `domains`, `status_codes`, plus per-role `networks.local.{subnet,dns_resolver}` (req-009). File root IS `applications.<app>.server`.        |
| `meta/rbac.yml`          | RBAC declarations. File root IS `applications.<app>.rbac`.                                                                                         |
| `meta/volumes.yml`       | Compose volumes. File root IS the volumes map keyed by volume name. No `compose:` and no `volumes:` wrapper.                                      |
| `meta/users.yml`         | Role-local user definitions. File root IS the users map (no `users:` wrapper).                                                                     |
| `meta/schema.yml`        | Credential schema (merged from the old `schema/main.yml` and the `credentials:` block of the old `config/main.yml`).                              |
| `meta/info.yml`          | Optional. Descriptive role-level metadata (`logo`, `homepage`, `video`, `display`) per req-011. File root IS `applications.<app>.info` (no `info:` wrapper). |
| `meta/variants.yml`      | Optional. Variant overrides deep-merged over the assembled application payload (used by `svc-ai-ollama`, `web-app-phpmyadmin`).                   |

Ansible only auto-loads `meta/main.yml`. Every other `meta/<topic>.yml` is
read by the project's own loaders (`utils/cache/applications.py`,
`utils/cache/users.py`, `utils/manager/inventory.py`).

## File-Root Convention 🧷

Every `meta/<topic>.yml` (except `meta/main.yml`, which keeps Galaxy semantics,
and `meta/schema.yml`, which is processed by `apply_schema()`) follows the
rule:

> **The file's content IS the value of `applications.<app>.<topic>`. There is
> NO wrapping key matching the filename.**

So `meta/services.yml` MUST NOT have a top-level `services:` key wrapping its
content; `meta/volumes.yml` MUST NOT have a top-level `volumes:` key; same for
`meta/server.yml`, `meta/rbac.yml`, `meta/users.yml`, `meta/info.yml`. The
filename alone fixes the path prefix in the materialised application tree,
which keeps consumer paths short and predictable (no redundant `compose.…`
prefixes).

## Materialised Paths 🔗

Consumers read the assembled application payload through
`lookup('applications', '<role>')` or `lookup('config', '<role>', '<dotted.path>')`.
The new paths are:

| Old path                              | New path                                |
|---------------------------------------|-----------------------------------------|
| `compose.services.<entity>.<…>`       | `services.<entity>.<…>`                 |
| `compose.volumes.<key>`               | `volumes.<key>`                         |
| `<top-level-key>.<…>` *(see inlining)*| `services.<primary_entity>.<top-level-key>.<…>` |

`credentials.*` paths remain unchanged because `apply_schema()` continues to
populate `applications.<app>.credentials.<…>`.

## Services Inlining Rule 📥

All top-level keys of the old `config/main.yml` *except* `compose:`, `server:`,
`rbac:`, and `credentials:` MUST be inlined into `meta/services.yml` under
`<primary_entity>.<key>`, where `<primary_entity>` is the value returned by
`get_entity_name(role_name)` (see [req-002](../../../requirements/002-service-registry-refactoring.md)).

Inlined keys observed today (non-exhaustive): `plugins`, `plugins_enabled`,
`email`, `ldap`, `accounts`, `scopes`, `alerting`, `addons`, `languages`,
`company`, `default_quota`, `legacy_login_mask`, `site_name`, `token`,
`modules`, `network`, `performance`, `preload_models`, `provision`,
`features`.

`compose.volumes:` is **not** inlined into services — it moves to its own
`meta/volumes.yml` (volumes are role-wide, not per-service).

### Worked Example — `web-app-matomo`

`get_entity_name('web-app-matomo') == 'matomo'`, so every former top-level
`config/main.yml` key (`site_name`, `performance`, …) is inlined under
`matomo.<key>`:

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

# After: roles/web-app-matomo/meta/services.yml  (file root IS the services map)
matomo:
  image: matomo
  site_name: "{{ ... }}"
  performance:
    workers: 4

# After: roles/web-app-matomo/meta/volumes.yml  (file root IS the volumes map)
data: matomo_data
```

## Schema Format — `meta/schema.yml` 🗝️

`meta/schema.yml` consolidates two structures that used to share the
`credentials:` top-level key but lived in different files:

1. The credential **schema definitions** from the old `schema/main.yml`
   (today flat, e.g. `alerting_telegram_bot_token: { description, algorithm,
   validation }`).
2. The credential **runtime values** from the `credentials:` block of the
   old `config/main.yml` (today nested, e.g. `recaptcha.key`,
   `recaptcha.secret`).

The unified schema supports:

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
  - When `default:` is present, the credential generator MUST NOT generate
    a new value via `algorithm:`; it writes the literal `default:` string
    verbatim.

### Worked Example — runtime credentials merged into `meta/schema.yml`

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
```

If a single role defines the same credential key in both the old
`schema/main.yml` and the `credentials:` block of the old `config/main.yml`,
the migration MUST stop and surface the collision instead of silently
merging.

## Per-Role Networks — `meta/server.yml.networks` 🌐

`networks:` is a top-level section of each role's `meta/server.yml`. The
file-root convention still applies (no wrapping `server:` key; file content
IS `applications.<app>.server`).

```yaml
# roles/<role>/meta/server.yml
# ... existing csp / domains / status_codes ...
networks:
  local:
    subnet: 192.168.101.112/28        # required; CIDR of the role's docker network
    dns_resolver: 192.168.102.29      # optional, only when a fixed DNS resolver IP is needed (today: mailu)
```

The role's name is implied by the path — there is NO `web-app-<role>` key
inside the file. The materialised path is
`applications.<role>.server.networks.local.{subnet,dns_resolver}`.

## Per-Entity Ports — `meta/services.yml.<entity>.ports` 🚪

Ports belong to the service entity that exposes them. All port data lives
under `<entity>.ports` in `meta/services.yml` (no `ports:` section in
`meta/server.yml`).

```yaml
# roles/<role>/meta/services.yml
<entity>:
  image: ...
  version: ...
  ports:
    inter: <int>                      # internal container port (single int)
    local:
      <category>: <int>               # localhost-bound host port
    public:
      <category>: <int>               # public-facing port
      relay:                          # for port-ranges (coturn, BBB, nextcloud TURN)
        start: <int>
        end:   <int>
```

### `inter` / `local` / `public` Split 🧭

| Slot      | Meaning                                                                                                       |
|-----------|---------------------------------------------------------------------------------------------------------------|
| `inter`   | **Internal container port.** Lives inside the container's network namespace, addressed by other containers on the same role-local network. NOT a host-bound port. Multiple roles MAY legitimately declare the same `inter` value (e.g. several nginx-based apps with `inter: 80`). |
| `local`   | **Localhost-bound host port.** Bound on `127.0.0.1` and only reachable through the front-proxy / SSH tunnels. The OS-level binding namespace is shared across all roles, so `local` values MUST be unique across the whole repo. |
| `public`  | **Public-facing host port.** Bound on `0.0.0.0` and exposed to the public internet (or to whatever the operator's firewall allows). Same uniqueness rule as `local`. |

### Always Category-Keyed Maps 🗂️

`ports.local` and `ports.public` are **always** category-keyed maps, even
when the map has only one entry. Polymorphic int-or-map values are NOT
supported. The category names are the same set as the legacy `09_ports.yml`:
`http`, `database`, `websocket`, `oauth2`, `ldap`, `ssh`, `ldaps`,
`stun_turn`, `stun_turn_tls`, `federation`, plus the structured `relay`
block under `public:`.

```yaml
gitea:
  ports:
    inter: 3000
    local:
      http: 8002          # category-keyed, even with one entry
    public:
      ssh: 2201
```

### `relay` — Port Ranges 📡

`ports.public.relay`, when present, is a map with two integer keys `start`
and `end` directly under `relay` (no nested entity-or-key sub-level), with
`start < end`. Only one relay range per entity is supported.

```yaml
coturn:
  ports:
    public:
      stun_turn:     3481
      stun_turn_tls: 5351
      relay:
        start: 20000
        end:   39999
```

### Multi-Entity Roles 🎛️

Each entity carries its own `ports` block:

```yaml
# roles/web-app-bluesky/meta/services.yml
api:
  ports: { local: { http: 8030 } }
web:
  ports: { local: { http: 8031 } }
view:
  ports: { local: { http: 8051 } }
```

### Port Bands 📊

The per-category port ranges that the suggester proposes from and that the
lint check enforces live as a single `PORT_BANDS` map in
[group_vars/all/08_networks.yml](../../../../group_vars/all/08_networks.yml).
Suggesters and lint pick up new entries automatically — no second
registration step. See `cli meta ports suggest` in
[ports-suggest.md](../../tools/ports-suggest.md).

## `run_after` and `lifecycle` 🌱

Both fields live on the role's **primary entity** in `meta/services.yml`,
where `<primary_entity> = get_entity_name(role_name)`:

```yaml
# roles/web-app-gitea/meta/services.yml
gitea:
  image: gitea/gitea
  ports: { ... }
  run_after:
    - svc-db-postgres
  lifecycle: stable
```

For multi-entity roles whose primary entity is not a real compose service
(e.g. `web-app-bluesky` → `bluesky`), the migration creates a dedicated
top-level metadata holder:

```yaml
# roles/web-app-bluesky/meta/services.yml
bluesky:                      # role-level metadata holder; no compose fields
  run_after:
    - web-app-keycloak
  lifecycle: alpha
api:
  ports: { ... }
  image: ...
web:
  ports: { ... }
  image: ...
```

### Allowed `lifecycle` Values

`planned`, `pre-alpha`, `alpha`, `beta`, `stable`, `deprecated`. Unknown
values fail the lint.

### `run_after` Rules

- `run_after:`, when present, is a non-empty list of role names.
- Empty `run_after: []` is **forbidden** — omit the key when no constraint
  exists.
- At most one entity per role carries `run_after` and `lifecycle`. Putting
  these fields on a non-primary entity fails the lint.

### Helper

The helper module `utils/roles/meta_lookup.py` exposes
`get_role_run_after(role) -> list[str]` and
`get_role_lifecycle(role) -> str | None`. All consumers of these fields use
the helper instead of hand-rolled derivations. The helper returns `[]` /
`None` gracefully when `meta/services.yml` is absent or when the field is
not set.

## Descriptive Role-Level Metadata — `meta/info.yml` 📝

Project-internal descriptive metadata (icon, upstream homepage, demo
video, dashboard display flag) lives in an OPTIONAL `meta/info.yml`,
not nested inside `galaxy_info:`. The file-root convention applies (no
wrapping `info:` key — file content IS `applications.<role>.info`). See
[req-011](../../../requirements/011-role-meta-info-migration.md).

```yaml
# roles/web-app-nextcloud/meta/info.yml
logo:
  class: fa-solid fa-cloud
homepage: https://nextcloud.com/
video: https://youtu.be/3jcYJGQgenI?si=FDmoMSrAb9_WvviC
```

### Allowed Fields

| Field      | Type   | Semantics                                                                                                                |
|------------|--------|--------------------------------------------------------------------------------------------------------------------------|
| `logo`     | map    | UI icon descriptor. Today only `class:` (FontAwesome). Future fields (`source:`, `svg:`) require an explicit allowlist update in the lint. |
| `homepage` | string | Upstream project URL — the canonical landing page of the software the role deploys.                                      |
| `video`    | string | Upstream demo / overview video URL.                                                                                      |
| `display`  | bool   | Default `true`. `false` opts the role out of dashboards / cards / apps grids.                                            |

The lint (`tests/lint/repository/test_role_meta_info.py`) rejects any
other top-level key so the file does not become a dumping ground.

### Optionality

`meta/info.yml` is OPTIONAL. A role with none of the four fields does
not grow the file. Consumers MUST treat missing file or missing field
as absent / default — matching the historical
`galaxy_info.get('display', True)` semantics.

### Materialised Path

```
applications.<role>.info.{logo,homepage,video,display}
```

The dashboard's `web-app-dashboard/lookup_plugins/docker_cards.py` reads
`logo.class` and `display` from this location; `description` and
`galaxy_tags` continue to come from `galaxy_info` (Galaxy-spec fields).

## Related Pages 📚

- [base.md](base.md) — service registration, loading, and injection model.
- [email.md](email.md) — email lookup contract.
- [ports-suggest.md](../../tools/ports-suggest.md) — `cli meta ports suggest` helper.
- [networks-suggest.md](../../tools/networks-suggest.md) — `cli meta networks suggest` helper.
- [req-008](../../../requirements/008-role-meta-layout.md) — meta layout spec.
- [req-009](../../../requirements/009-per-role-networks-and-ports.md) — per-role networks and ports spec.
- [req-010](../../../requirements/010-role-meta-runafter-lifecycle-migration.md) — `run_after` / `lifecycle` migration spec.
- [req-011](../../../requirements/011-role-meta-info-migration.md) — `meta/info.yml` migration spec.
