# Per-Role Meta Layout 🗂️

This page describes the on-disk shape of every role's metadata.
All role-owned metadata lives under `roles/<role>/meta/<topic>.yml`.

## File Layout 📁

| File                     | Contents                                                                                                                                          |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `meta/main.yml`          | Ansible Galaxy metadata + Ansible `dependencies:`. No project-internal `run_after:` / `lifecycle:` keys, no `logo:` / `homepage:` / `video:` / `display:`. |
| `meta/services.yml`      | Per-entity service config. **File root IS the services map** keyed by `<entity_name>`. No `compose:` and no `services:` wrapper.                  |
| `meta/server.yml`        | CSP, `domains`, `status_codes`, plus per-role `networks.local.{subnet,dns_resolver}`. File root IS `applications.<app>.server`.                   |
| `meta/rbac.yml`          | RBAC declarations. File root IS `applications.<app>.rbac`.                                                                                         |
| `meta/volumes.yml`       | Compose volumes. File root IS the volumes map keyed by volume name. No `compose:` and no `volumes:` wrapper.                                      |
| `meta/users.yml`         | Role-local user definitions. File root IS the users map (no `users:` wrapper).                                                                     |
| `meta/schema.yml`        | Credential schema definitions and runtime credential values.                                                                                       |
| `meta/info.yml`          | Optional. Descriptive role-level metadata (`logo`, `homepage`, `video`, `display`). File root IS `applications.<app>.info` (no `info:` wrapper). |
| `meta/variants.yml`      | Optional. Variant overrides deep-merged over the assembled application payload (used by `svc-ai-ollama`, `web-app-phpmyadmin`).                   |

Ansible only auto-loads `meta/main.yml`.
Every other `meta/<topic>.yml` is read by the project's own loaders (`utils/cache/applications.py`, `utils/cache/users.py`, `utils/manager/inventory.py`).

## File-Root Convention 🧷

Every `meta/<topic>.yml` (except `meta/main.yml`, which keeps Galaxy semantics, and `meta/schema.yml`, which is processed by `apply_schema()`) follows the rule:

> **The file's content IS the value of `applications.<app>.<topic>`. There is NO wrapping key matching the filename.**

So `meta/services.yml` MUST NOT have a top-level `services:` key wrapping its content.
`meta/volumes.yml` MUST NOT have a top-level `volumes:` key, and the same rule applies to `meta/server.yml`, `meta/rbac.yml`, `meta/users.yml`, and `meta/info.yml`.
The filename alone fixes the path prefix in the materialised application tree, which keeps consumer paths short and predictable (no redundant `compose.…` prefixes).

## Materialised Paths 🔗

Consumers read the assembled application payload through `lookup('applications', '<role>')` or `lookup('config', '<role>', '<dotted.path>')`.
The paths are:

| Source                                | Materialised path                                |
|---------------------------------------|--------------------------------------------------|
| `meta/services.yml.<entity>.<…>`      | `services.<entity>.<…>`                          |
| `meta/volumes.yml.<key>`              | `volumes.<key>`                                  |
| `meta/services.yml.<primary_entity>.<top-level-key>.<…>` | `services.<primary_entity>.<top-level-key>.<…>` |

`credentials.*` paths are populated by `apply_schema()` at `applications.<app>.credentials.<…>`.

## Services Inlining Rule 📥

All non-compose top-level keys (everything except `compose:`, `server:`, `rbac:`, and `credentials:`) MUST be inlined into `meta/services.yml` under `<primary_entity>.<key>`, where `<primary_entity>` is the value returned by `get_entity_name(role_name)`.

Inlined keys observed today (non-exhaustive): `plugins`, `plugins_enabled`, `email`, `ldap`, `accounts`, `scopes`, `alerting`, `addons`, `languages`, `company`, `default_quota`, `legacy_login_mask`, `site_name`, `token`, `modules`, `network`, `performance`, `preload_models`, `provision`, `features`.

`compose.volumes:` is **not** inlined into services.
It moves to its own `meta/volumes.yml` (volumes are role-wide, not per-service).

### Worked Example: `web-app-matomo`

`get_entity_name('web-app-matomo') == 'matomo'`, so every former top-level `config/main.yml` key (`site_name`, `performance`, …) is inlined under `matomo.<key>`:

```yaml
# roles/web-app-matomo/meta/services.yml  (file root IS the services map)
matomo:
  image: matomo
  site_name: "{{ ... }}"
  performance:
    workers: 4

# roles/web-app-matomo/meta/volumes.yml  (file root IS the volumes map)
data: matomo_data
```

## Schema Format: `meta/schema.yml` 🗝️

`meta/schema.yml` consolidates two structures under the `credentials:` top-level key:

1. The credential **schema definitions** (flat keys, e.g. `alerting_telegram_bot_token: { description, algorithm, validation }`).
2. The credential **runtime values** (nested keys, e.g. `recaptcha.key`, `recaptcha.secret`).

The unified schema supports:

- **Nested keys.** Both flat and nested credential keys are accepted, so e.g. `recaptcha.key` and `recaptcha.secret` remain nested.
- **`algorithm:` defaults to `plain`** when the field is omitted.
- **`default:` (optional)** is a Jinja string used as the credential's value when the inventory does not provide one.
  - `default:` is **NOT rendered at inventory creation time.** The literal Jinja string is written verbatim into the inventory so that referenced variables (`CAPTCHA.RECAPTCHA.KEY`, `lookup(...)`, …) resolve only at deploy/runtime when those variables are actually defined.
  - `default:` values are **NOT validated.** `validation:` only applies to user-provided values, so the schema default is exempt.
  - When `default:` is present, the credential generator MUST NOT generate a new value via `algorithm:`. It writes the literal `default:` string verbatim.

### Worked Example: runtime credentials in `meta/schema.yml`

```yaml
# roles/web-app-keycloak/meta/schema.yml
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

Flat schema entries keep the same shape:

```yaml
# roles/web-app-prometheus/meta/schema.yml
credentials:
  alerting_telegram_bot_token:
    description: "Telegram bot token for Alertmanager notifications."
    algorithm:   token
    validation:  non_empty_string
```

If a single role defines the same credential key in both a schema definition and a runtime value, the loader MUST stop and surface the collision instead of silently merging.

## Per-Role Networks: `meta/server.yml.networks` 🌐

`networks:` is a top-level section of each role's `meta/server.yml`.
The file-root convention applies: there is no wrapping `server:` key, and the file content IS `applications.<app>.server`.

```yaml
# roles/<role>/meta/server.yml
# ... existing csp / domains / status_codes ...
networks:
  local:
    subnet: 192.168.101.112/28        # required; CIDR of the role's docker network
    dns_resolver: 192.168.102.29      # optional, only when a fixed DNS resolver IP is needed (today: mailu)
```

The role's name is implied by the path.
There is NO `web-app-<role>` key inside the file.
The materialised path is `applications.<role>.server.networks.local.{subnet,dns_resolver}`.

## Per-Entity Ports: `meta/services.yml.<entity>.ports` 🚪

Ports belong to the service entity that exposes them.
All port data lives under `<entity>.ports` in `meta/services.yml` (no `ports:` section in `meta/server.yml`).

```yaml
# roles/<role>/meta/services.yml
<entity>:
  image: ...
  version: ...
  ports:
    internal:
      <category>: <int>               # internal container port (category-keyed)
    local:
      <category>: <int>               # localhost-bound host port
    public:
      <category>: <int>               # public-facing port
      relay:                          # for port-ranges (coturn, BBB, nextcloud TURN)
        start: <int>
        end:   <int>
```

### `internal` / `local` / `public` Split 🧭

| Slot       | Meaning                                                                                                       |
|------------|---------------------------------------------------------------------------------------------------------------|
| `internal` | **Internal container port.** Lives inside the container's network namespace, addressed by other containers on the same role-local network. NOT a host-bound port. Multiple roles MAY legitimately declare the same value (e.g. several nginx-based apps with `internal: { http: 80 }`). |
| `local`    | **Localhost-bound host port.** Bound on `127.0.0.1` and only reachable through the front-proxy / SSH tunnels. The OS-level binding namespace is shared across all roles, so `local` values MUST be unique across the whole repo. |
| `public`   | **Public-facing host port.** Bound on `0.0.0.0` and exposed to the public internet (or to whatever the operator's firewall allows). Same uniqueness rule as `local`. |

### Always Category-Keyed Maps 🗂️

`ports.internal`, `ports.local` and `ports.public` are **always** category-keyed maps, even when the map has only one entry.
Polymorphic int-or-map values are NOT supported.
The category names are: `http`, `database`, `websocket`, `oauth2`, `ldap`, `ssh`, `ldaps`, `stun_turn`, `stun_turn_tls`, `federation`, plus the structured `relay` block under `public:`.

```yaml
gitea:
  ports:
    internal:
      http: 3000          # category-keyed, even with one entry
    local:
      http: 8002
    public:
      ssh: 2201
```

### `relay` Port Ranges 📡

`ports.public.relay`, when present, is a map with two integer keys `start` and `end` directly under `relay` (no nested entity-or-key sub-level), with `start < end`.
Only one relay range per entity is supported.

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

The per-category port ranges that the suggester proposes from and that the lint check enforces live as a single `PORT_BANDS` map in [group_vars/all/08_networks.yml](../../../../../group_vars/all/08_networks.yml).
Suggesters and lint pick up new entries automatically, with no second registration step.
See `cli contributing network ports suggest` in [port.md](../../../tools/network/port.md).

## `run_after` and `lifecycle` 🌱

For the semantic meaning of each `lifecycle` value (and the criteria a role MUST satisfy to claim a given value) see [lifecycle.md](lifecycle.md).
This section only covers the on-disk shape of the two fields.

Both fields live on the role's **primary entity** in `meta/services.yml`, where `<primary_entity> = get_entity_name(role_name)`:

```yaml
# roles/web-app-gitea/meta/services.yml
gitea:
  image: gitea/gitea
  ports: { ... }
  run_after:
    - svc-db-postgres
  lifecycle: stable
```

For multi-entity roles whose primary entity is not a real compose service (e.g. `web-app-bluesky` → `bluesky`), the layout uses a dedicated top-level metadata holder:

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

`planned`, `pre-alpha`, `alpha`, `beta`, `stable`, `deprecated`. Unknown values fail the lint.

### `run_after` Rules

- `run_after:`, when present, is a non-empty list of role names.
- Empty `run_after: []` is **forbidden**: omit the key when no constraint exists.
- At most one entity per role carries `run_after` and `lifecycle`.
  Putting these fields on a non-primary entity fails the lint.

### Helper

The helper module `utils/roles/meta_lookup.py` exposes `get_role_run_after(role) -> list[str]` and `get_role_lifecycle(role) -> str | None`.
All consumers of these fields use the helper instead of hand-rolled derivations.
The helper returns `[]` / `None` gracefully when `meta/services.yml` is absent or when the field is not set.

## Descriptive Role-Level Metadata: `meta/info.yml` 📝

Project-internal descriptive metadata (icon, upstream homepage, demo video, dashboard display flag) lives in an OPTIONAL `meta/info.yml`, not nested inside `galaxy_info:`.
The file-root convention applies: there is no wrapping `info:` key, and the file content IS `applications.<role>.info`.

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
| `homepage` | string | Upstream project URL: the canonical landing page of the software the role deploys.                                      |
| `video`    | string | Upstream demo / overview video URL.                                                                                      |
| `display`  | bool   | Default `true`. `false` opts the role out of dashboards / cards / apps grids.                                            |

The lint (`tests/lint/ansible/roles/meta/test_info.py`) rejects any other top-level key so the file does not become a dumping ground.

### Optionality

`meta/info.yml` is OPTIONAL.
A role with none of the four fields does not grow the file.
Consumers MUST treat a missing file or missing field as absent / default, and `display` defaults to `true`.

### Materialised Path

```
applications.<role>.info.{logo,homepage,video,display}
```

The dashboard's `web-app-dashboard/lookup_plugins/docker_cards.py` reads `logo.class` and `display` from this location, while `description` and `galaxy_tags` continue to come from `galaxy_info` (Galaxy-spec fields).

## Related Pages 📚

- [base.md](base.md) covers the service registration, loading, and injection model.
- [email.md](email.md) covers the email lookup contract.
- [port.md](../../../tools/network/port.md) describes the `cli contributing network ports suggest` helper.
- [address.md](../../../tools/network/address.md) describes the `cli contributing network address suggest` helper.
