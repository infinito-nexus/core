# Service Management 🧱

This page is the SPOT for how shared services are declared, discovered, ordered,
loaded, and injected.

## What Is a Service? 🧩

A service is a reusable dependency that an application enables via
`services.<service_key>`.

Examples:
- `web-svc-cdn` provides the primary service key `cdn`
- `web-app-keycloak` provides `oidc`
- `svc-db-mariadb` provides `mariadb`

Each service entry lives in the provider role's own
[meta/services.yml](../../../../roles) — the file root IS the services map
keyed by `<entity_name>` (no `compose:` and no `services:` wrapper). See
[layout.md](layout.md) for the full per-role meta layout.

## Role-Local Service Metadata 🏷️

Service providers are self-describing. The provider role owns:
- `enabled`
- `shared`
- optional `provides`
- optional `canonical`

Example (file root of `meta/services.yml`):

```yaml
keycloak:
  enabled: false
  shared: true
  provides: oidc
```

Canonical aliases are also role-local:

```yaml
cdn:
  enabled: false
  shared: true
css:
  enabled: true
  shared: true
  canonical: cdn
javascript:
  enabled: true
  shared: true
  canonical: cdn
```

Rules:
- The primary service entry is the role entity name returned by `get_entity_name`.
- `provides:` is only used when the public service name differs from the entity name.
- `canonical:` is only used on alias entries that resolve back to the primary service key.
- `frontend` vs. `backend` is derived from the role name prefix, not stored in config.

## Service Discovery 🔍

Service discovery is built from role configs, not from a central registry file.

Primary implementation files:
- [service_registry.py](../../../../utils/service_registry.py)
- [service_registry.py lookup plugin](../../../../plugins/lookup/service_registry.py)

The discovery layer:
- scans role configs from [roles/](../../../../roles)
- discovers provider entries from `services`
- derives deploy type and loader bucket from the role name
- resolves `provides:` and `canonical:`
- validates and applies `run_after:` from `meta/services.yml.<primary_entity>` (per [req-010](../../../requirements/010-role-meta-runafter-lifecycle-migration.md))

## Load Order 🧮

[main.yml](../../../../roles/sys-utils-service-loader/tasks/main.yml)
is the single loader SPOT for all shared services.

It runs from [01_constructor.yml](../../../../tasks/stages/01_constructor.yml)
before the normal application stage.

Global bucket order:
1. `universal`
2. `workstation`
3. `server`
4. `web-svc`
5. `web-app`

Within the same bucket, ordering is refined by `run_after:` declared on the
provider role's primary entity in
[meta/services.yml](../../../../roles) (i.e. `services.<primary_entity>.run_after`,
per [req-010](../../../requirements/010-role-meta-runafter-lifecycle-migration.md)).

Rules:
- `run_after:` entries are role names, not service keys.
- Cross-type `run_after:` is invalid and fails hard.
- Later-bucket dependencies are invalid and fail hard.
- Cross-type service dependencies do not need `run_after:` because constructor-stage
  loading already brings backend services up before normal app deployment.

## Loading vs Injection 🔀

Service loading and frontend injection are separate mechanisms.

### Loading 📥

Loading decides whether the provider role is deployed at all.

[main.yml](../../../../roles/sys-utils-service-loader/tasks/main.yml):
- queries the ordered discovered service list
- checks `lookup('service', service_key).required`
- skips roles already protected by `run_once_*`
- loads services through [load_app.yml](../../../../tasks/utils/load_app.yml)

Frontend service probe/load helper:
- [load_service.yml](../../../../roles/sys-utils-service-loader/tasks/load_service.yml)

### Injection 🔌

Injection decides whether a deployed app gets extra nginx integration such as
dashboard, logout, CSS, or JavaScript hooks.

This stays in:
- [main.yml](../../../../roles/sys-front-inj-all/tasks/main.yml)
- [inj_enabled.py](../../../../roles/sys-front-inj-all/filter_plugins/inj_enabled.py)

Injection still reads the current app's `services.<feature>.enabled` flags.
It does not load provider roles.

## Lookup Plugins 🔎

### `service` 🧷

File:
[service.py](../../../../plugins/lookup/service.py)

Examples:

```yaml
lookup('service', 'matomo')
lookup('service', 'oidc')
lookup('service', 'web-svc-cdn')
```

Returns:
- `id`
- `role`
- `enabled`
- `shared`
- `required` — True when some deployed app has the service with both
  `enabled: true` AND `shared: true`, directly or transitively through its
  own enabled service dependencies. This is the flag consumers should gate
  on when deciding whether to load, integrate with, or configure the
  service — a plain `enabled` flag is not enough on its own, because a
  service that is enabled but never shared with another app is not actually
  contractually required by anyone.

Behavior:
- accepts either a service key or a provider role name
- resolves aliases through `canonical`
- resolves provider roles through discovered primary service keys
- computes `required` transitively from enabled shared services

### `service_registry` 📚

File:
[service_registry.py](../../../../plugins/lookup/service_registry.py)

Examples:

```yaml
query('service_registry') | first
query('service_registry', 'ordered') | first
```

Modes:
- default: full discovered registry mapping
- `ordered`: ordered primary service entries for the service loader

### `applications_current_play` 🧭

File:
[applications_current_play.py](../../../../plugins/lookup/applications_current_play.py)

Builds the current-play application set including:
- group-selected roles
- transitive shared service dependencies
- meta dependencies

## Database Services 🗄️

Relational databases are regular services now:
- `svc-db-mariadb` provides `mariadb`
- `svc-db-postgres` provides `postgres`

Applications express database choice directly via the file root of
`meta/services.yml`:

```yaml
mariadb:
  enabled: true
  shared: true
```

or:

```yaml
postgres:
  enabled: true
  shared: false
```

The `lookup('database', ...)` API remains as the convenience accessor for database
connection values, but it now resolves the active direct database service from those
role-local keys instead of `services.database.type`.

## Related Files 📁

| File | Purpose |
|---|---|
| [service_registry.py](../../../../utils/service_registry.py) | Service discovery, `provides`, `canonical`, bucket detection, `run_after` ordering |
| [service_registry.py lookup](../../../../plugins/lookup/service_registry.py) | Exposes the discovered registry and ordered provider list to Ansible |
| [service.py](../../../../plugins/lookup/service.py) | Resolves service flags and transitive need |
| [applications_current_play.py](../../../../plugins/lookup/applications_current_play.py) | Builds the current play app graph with shared service deps |
| [main.yml](../../../../roles/sys-utils-service-loader/tasks/main.yml) | Single shared-service loader SPOT |
| [load_service.yml](../../../../roles/sys-utils-service-loader/tasks/load_service.yml) | Per-service load helper used by the central service loader |
| [01_constructor.yml](../../../../tasks/stages/01_constructor.yml) | Calls the service loader during constructor |
| [load_app.yml](../../../../tasks/utils/load_app.yml) | Run-once role loader |
| [test_service_registry.py](../../../../tests/unit/utils/test_service_registry.py) | Unit tests for discovery, buckets, and `run_after` ordering |
| [test_service.py](../../../../tests/unit/plugins/lookup/test_service.py) | Unit tests for `lookup('service', ...)` |
| [test_resolvable.py](../../../../tests/integration/services/test_resolvable.py) | Integration checks for discovered service resolution |
| [test_canonical.py](../../../../tests/integration/services/test_canonical.py) | Canonical alias consistency checks |
| [test_transitive_dependencies.py](../../../../tests/integration/services/test_transitive_dependencies.py) | Integration coverage for transitive dependency resolution |
