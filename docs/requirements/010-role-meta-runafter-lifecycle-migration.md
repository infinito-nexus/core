# 010 - Role Meta `run_after` / `lifecycle` Migration

## User Story

As a contributor, I want every role's `run_after:` (project-specific load
ordering, per req-002) and `lifecycle:` (role maturity marker) to live
alongside the rest of the role's service metadata under
`meta/services.yml.<primary_entity>` instead of being nested inside
`meta/main.yml.galaxy_info`, so that the role's data shape is consistent
(everything role-specific lives under `meta/services.yml`) and Ansible
Galaxy metadata in `meta/main.yml` is no longer mixed with project-internal
fields.

## Dependencies

This requirement is a follow-up to and depends on **both**
[008 — Role Meta Layout Refactoring](008-role-meta-layout.md) **and**
[009 — Per-Role Networks and Ports Migration](009-per-role-networks-and-ports.md).
Req-008 and Req-009 MUST both be fully merged (every Acceptance Criterion
checked off) before this requirement is started. The per-role `meta/services.yml`
shape (file root keyed by `<entity_name>`, materialised at
`applications.<app>.services.<entity>.<…>`, including the per-entity
`ports`/`networks` introduced by Req-009) is treated as given.

## Background

Today, two project-specific fields live nested inside
`meta/main.yml.galaxy_info` alongside Ansible-standard Galaxy metadata:

```yaml
# roles/desk-gnome-caffeine/meta/main.yml (today)
galaxy_info:
  author: Kevin Veen-Birkenbach
  description: ...
  license: ...
  galaxy_tags:
  - caffeine
  - autostart
  - archlinux
  run_after:
  - desk-gnome
  lifecycle: pre-alpha
```

- **`run_after:`** is the project-specific role-load-order list introduced by
  req-002. `roles/sys-utils-service-loader` reads it to order role loads
  within a deploy-type pass.
- **`lifecycle:`** is a maturity marker (`pre-alpha`, `alpha`, `beta`,
  `stable`, …) used by `cli meta roles lifecycle_filter` and other
  introspection commands to filter or report on role status.

Bundling these under `galaxy_info` mixes Ansible-standard fields with
project-internal ones; Galaxy publishers ignore unknown keys, so the values
have always lived there as a workaround. With req-008 we now have a
project-owned location for per-role/per-entity metadata
(`meta/services.yml`), and these two fields belong there.

## Target Layout

Both fields move to `meta/services.yml` under the role's **primary entity**,
where `<primary_entity>` is the value returned by `get_entity_name(role_name)`
(per req-002 — strip the deploy-type prefix `web-app-`, `web-svc-`, `svc-`,
`sys-`, `desk-`, `dev-`, `drv-`, `gen-` from the role name).

```yaml
# roles/<role>/meta/services.yml
<primary_entity>:
  # ... existing service config from req-008/009 (image, ports, etc.) ...
  run_after:
    - <other-role>
  lifecycle: pre-alpha
```

`meta/main.yml.galaxy_info` retains only Ansible-standard fields after the
migration (no `run_after:`, no `lifecycle:`).

### Worked Examples

**Single-entity role (`desk-gnome-caffeine`, primary entity `gnome-caffeine`):**

```yaml
# Before: roles/desk-gnome-caffeine/meta/main.yml
galaxy_info:
  ...
  galaxy_tags: [caffeine, autostart, archlinux]
  run_after:
    - desk-gnome
  lifecycle: pre-alpha

# After: roles/desk-gnome-caffeine/meta/main.yml
galaxy_info:
  ...
  galaxy_tags: [caffeine, autostart, archlinux]

# After: roles/desk-gnome-caffeine/meta/services.yml
gnome-caffeine:
  run_after:
    - desk-gnome
  lifecycle: pre-alpha
```

For desk/dev/drv/gen roles that have no compose services today, the primary
entity entry in `meta/services.yml` may carry **only** the role-level
metadata fields (`run_after`, `lifecycle`); no compose-shaped fields are
required.

**Single-entity service role (`web-app-gitea`, primary entity `gitea`):**

```yaml
# After: roles/web-app-gitea/meta/services.yml
gitea:
  image: gitea/gitea
  ports: { ... }              # from req-009
  run_after:
    - svc-db-postgres
  lifecycle: stable
```

**Multi-entity role (`web-app-bluesky`, primary entity `bluesky`, compose
entities `api`/`web`/`view`):**

The primary entity returned by `get_entity_name('web-app-bluesky')` is
`bluesky`, but bluesky has no compose service named `bluesky` — only
`api`, `web`, `view`. The migration creates a dedicated `bluesky:` top-level
entry in `meta/services.yml` to host the role-level metadata; the existing
compose entities stay alongside it untouched.

```yaml
# After: roles/web-app-bluesky/meta/services.yml
bluesky:                      # role-level metadata holder; no compose fields
  run_after:
    - web-app-keycloak
  lifecycle: alpha
api:
  ports: { ... }              # actual compose entity (req-009)
  image: ...
web:
  ports: { ... }
  image: ...
view:
  ports: { ... }
  image: ...
```

This keeps the placement uniform (`services.<primary_entity>.run_after`) for
every role, regardless of whether the primary entity is a real compose
service or a logical role-level holder.

## Materialised Tree and Consumer Path Rewrites

| Old path                                       | New path                                                              |
|------------------------------------------------|-----------------------------------------------------------------------|
| `<meta/main.yml>.galaxy_info.run_after`        | `applications.<role>.services.<primary_entity>.run_after`             |
| `<meta/main.yml>.galaxy_info.lifecycle`        | `applications.<role>.services.<primary_entity>.lifecycle`             |

Cross-role consumers that today read `<role>'s meta/main.yml` directly to
extract `run_after` / `lifecycle` MUST be rewritten to look the value up
through the new path. A small helper SHOULD be introduced (e.g.
`get_role_run_after(role)` / `get_role_lifecycle(role)`) that resolves
`get_entity_name(role)` and reads the field — this avoids hard-coding the
primary-entity derivation at every call site.

## Acceptance Criteria

### File migration

- [ ] Every role that has a `run_after:` field nested under
      `meta/main.yml.galaxy_info` has that list moved verbatim to
      `meta/services.yml.<primary_entity>.run_after`. The
      `galaxy_info.run_after` key is removed from `meta/main.yml`.
- [ ] Every role that has a `lifecycle:` field nested under
      `meta/main.yml.galaxy_info` has that string moved verbatim to
      `meta/services.yml.<primary_entity>.lifecycle`. The
      `galaxy_info.lifecycle` key is removed from `meta/main.yml`.
- [ ] `<primary_entity>` is derived via `get_entity_name(role_name)` (the
      same function used by `sys-utils-service-loader` per req-002).
- [ ] For roles where `<primary_entity>` does not exist as a compose entity
      in `meta/services.yml` today (e.g. `web-app-bluesky` → `bluesky`,
      `web-app-matrix` → `matrix`, desk/dev/drv/gen roles with no compose
      services), the migration creates a dedicated top-level entry under
      `<primary_entity>` carrying only the migrated `run_after` and/or
      `lifecycle` fields.
- [ ] After migration, no `meta/main.yml` in the repository contains a
      `run_after:` or `lifecycle:` key (under `galaxy_info` or anywhere
      else).

### Schema rules

- [ ] `meta/services.yml.<entity>.run_after`, when present, is a non-empty
      list of role names (strings). Empty lists are not allowed; if a role
      has no ordering constraint, the field is omitted entirely.
- [ ] `meta/services.yml.<entity>.lifecycle`, when present, is a single
      string from the documented allow-list: `planned`, `pre-alpha`,
      `alpha`, `beta`, `stable`, `deprecated`. The first four cover every
      value currently in use across `roles/*/meta/main.yml` (`planned`,
      `pre-alpha`, `alpha`, `beta`); `stable` and `deprecated` are
      forward-compatible additions for roles that graduate or get retired.
      Unknown values fail the lint.
- [ ] Inline YAML comments next to `lifecycle:` values today
      (e.g. `lifecycle: alpha # SSO integration missing`) are NOT
      preserved by the migration — the value (`alpha`) moves verbatim,
      the comment is dropped. If the comment carries information worth
      keeping, the contributor MUST move it into the role's `README.md`
      or `AGENTS.md` before running the migration.
- [ ] At most one entity per role carries `run_after` and `lifecycle`. If
      these fields appear on a non-primary entity (e.g. on `api` instead of
      `bluesky` for `web-app-bluesky`), the lint fails.

### Code consumer updates

The following consumers read `run_after` and/or `lifecycle` from
`meta/main.yml` today and MUST be updated to read from
`meta/services.yml.<primary_entity>` (via the new helper or directly):

- [ ] `utils/roles/dependency_resolver.py`
- [ ] `utils/service_registry.py`
- [ ] `utils/invokable.py`
- [ ] `roles/sys-utils-service-loader` (its tasks/templates that drive the
      load-order pass)
- [ ] `cli/meta/applications/resolution/run_after/__main__.py`
- [ ] `cli/meta/roles/lifecycle_filter/__main__.py`
- [ ] `cli/meta/applications/resolution/combined/__main__.py`
- [ ] `cli/meta/applications/resolution/combined/resolver.py`
- [ ] `cli/meta/applications/resolution/combined/role_introspection.py`
- [ ] `cli/meta/applications/resolution/combined/tree.py`
- [ ] `cli/meta/applications/resolution/combined/errors.py`
- [ ] `cli/meta/applications/type/__main__.py`
- [ ] `cli/build/tree/__main__.py`
- [ ] `cli/build/graph/__main__.py`
- [ ] `cli/build/role_include/__main__.py`
- [ ] `cli/deploy/development/common.py`
- [ ] `cli/deploy/development/init.py`
- [ ] `cli/deploy/development/deps.py`
- [ ] `cli/deploy/development/deploy.py`
- [ ] `plugins/filter/canonical_domains_map.py`
- [ ] any other consumer discovered during migration that reads
      `run_after` or `lifecycle` from `meta/main.yml`.

### Helper

- [ ] A helper module (e.g. `utils/roles/meta_lookup.py`) exposes
      `get_role_run_after(role) -> list[str]` and
      `get_role_lifecycle(role) -> str | None` that resolve
      `get_entity_name(role)` once and read the value from the role's
      `meta/services.yml`. All consumers above use the helper instead of
      hand-rolled derivations.
- [ ] The helper returns `[]` / `None` gracefully when **either** the field
      is absent **or** the role's `meta/services.yml` does not exist (some
      roles legitimately have neither `run_after`, `lifecycle`, nor compose
      services and so never grow a `meta/services.yml`). It raises a clear
      error only when `meta/services.yml` exists but is malformed
      (unparseable YAML, wrong root shape, etc.).

### Consumer rewrites

- [ ] A repository-wide `grep` for `galaxy_info.run_after`,
      `galaxy_info.lifecycle`, and the bare keys `run_after:` /
      `lifecycle:` directly under `galaxy_info:` in `meta/main.yml` MUST
      return zero matches after the refactor (outside this requirement file
      and historical changelogs).
- [ ] No legacy fallback to `meta/main.yml.galaxy_info` is implemented; the
      new path is the single source of truth.

### Tests

- [ ] Unit tests cover the helper's behaviour on:
      - a service role with `run_after` and `lifecycle` on its primary
        entity;
      - a multi-entity role (e.g. bluesky) where the primary entity is a
        dedicated metadata holder;
      - a role with no `run_after` (returns `[]`);
      - a role with no `lifecycle` (returns `None`);
      - a role with malformed `meta/services.yml` (raises a clear error).
- [ ] Integration tests assert that for every existing role, the
      materialised `applications.<role>.services.<primary_entity>.run_after`
      and `…lifecycle` resolve to the same values that
      `meta/main.yml.galaxy_info.run_after` / `…lifecycle` had before the
      migration.
- [ ] A new lint test under `tests/lint/` MUST fail if any of the
      following conditions occur:
      - a `run_after:` or `lifecycle:` key reappears anywhere in
        `meta/main.yml`;
      - `meta/services.yml.<entity>.lifecycle` carries a value not in the
        allowed set (`planned`, `pre-alpha`, `alpha`, `beta`, `stable`,
        `deprecated`);
      - `run_after` or `lifecycle` appears on a non-primary entity within
        the same role's `meta/services.yml`;
      - a `run_after` list is empty (`[]`) instead of being omitted.

### Documentation

- [ ] `docs/contributing/design/services/` documents the new placement
      (`meta/services.yml.<primary_entity>.{run_after,lifecycle}`) and the
      allowed `lifecycle` values.
- [ ] Any reference in `docs/contributing/` or `docs/agents/` to the old
      `galaxy_info.run_after` / `galaxy_info.lifecycle` location is
      rewritten to the new path.
- [ ] Role-level `AGENTS.md` files that mention either field point at the
      new location.

### Atomicity & validation

- [ ] The migration MUST land as a single atomic change set: file moves,
      consumer rewrites, helper introduction, tests, and docs ship
      together so no intermediate commit leaves the tree in a half-migrated
      state.
- [ ] `make test` passes after the refactor with no skipped suites.
- [ ] Every file and role touched by this refactoring is also simplified
      and refactored where possible, following the principles in
      [principles.md](../contributing/design/principles.md).

## Validation Apps

The following selection covers all relevant migration patterns and MUST
deploy end to end after the refactor:

| App                        | Why it's in the validation set                                                                           |
|----------------------------|----------------------------------------------------------------------------------------------------------|
| `web-app-gitea`            | Single-entity service role; `run_after` + `lifecycle` on a real compose entity.                          |
| `web-app-bluesky`          | Multi-entity role where the primary entity (`bluesky`) is a metadata-only holder alongside `api`/`web`/`view`. |
| `web-app-matrix`           | Multi-entity role (`synapse`/`element`); primary entity `matrix` is a metadata-only holder.              |
| `web-app-nextcloud`        | Complex role with multiple `run_after` dependencies; exercises the dependency resolver path.             |

```bash
APPS="web-app-gitea web-app-bluesky web-app-matrix web-app-nextcloud" \
  make deploy-fresh-purged-apps
```

## Migration Notes

- The migration is mechanical: read the two fields from each role's
  `meta/main.yml.galaxy_info`, write them to the role's
  `meta/services.yml.<primary_entity>`, delete the originals.
- For roles whose `meta/services.yml` does not yet have an entry for the
  primary entity (multi-entity roles like bluesky/matrix, or non-compose
  roles like desk/dev/drv/gen), the migration creates the entry; existing
  compose entities are not touched.
- The `lifecycle` allowed-set (`planned`, `pre-alpha`, `alpha`, `beta`,
  `stable`, `deprecated`) is anchored on the four values actually present
  in `roles/*/meta/main.yml` today (`planned`, `pre-alpha`, `alpha`, `beta`);
  `stable` and `deprecated` are forward-compatible. If migration discovers
  any value outside this set, the agent MUST stop and surface the unknown
  value rather than silently mapping or dropping it.
- This requirement does NOT touch any other field in `meta/main.yml`.
  `galaxy_info`, `dependencies`, and (per req-002) the explicit Ansible
  `dependencies:` list stay where they are.

## Prerequisites

Before starting any implementation work, you MUST read [AGENTS.md](../../AGENTS.md)
and follow all instructions in it. You MUST also confirm that **both**
requirement 008 **and** requirement 009 are fully merged (every Acceptance
Criterion checked off); this requirement treats req-008's `meta/services.yml`
shape and req-009's per-entity `ports`/`networks` placement as given.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications
only when a decision is genuinely ambiguous and would otherwise block
progress; default to the intent already captured in this document and
proceed. Avoid back-and-forth questions on choices that are already
specified above (target placement, primary-entity derivation, allowed
`lifecycle` values, single-source rule).

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Land the refactor in a single atomic branch:
   1. Introduce the helper (`get_role_run_after`, `get_role_lifecycle`)
      plus its unit tests against synthetic fixtures.
   2. Update every consumer listed under "Code consumer updates" to use
      the helper.
   3. Migrate `meta/main.yml.galaxy_info.{run_after,lifecycle}` to
      `meta/services.yml.<primary_entity>.{run_after,lifecycle}` across
      every affected role in one mechanical pass; create the primary-entity
      holder where it does not exist yet.
   4. Remove the now-empty `run_after:` / `lifecycle:` keys from
      `meta/main.yml`.
   5. Add the lint test that prevents the old location from coming back.
   6. Update tests, fixtures, and docs.
3. Run `make test` until green.
4. Run the validation deploy listed above.

## Final Iteration

After the changes are implemented in the working tree and an initial
`make test` run completes, the agent MUST iterate **autonomously** end-to-end
following [Role Loop](../agents/action/iteration/role.md) against the
following two apps (in order):

1. `web-app-nextcloud`     — most `run_after` dependencies; stresses the
   dependency resolver path.
2. `web-app-bluesky`       — multi-entity role with a metadata-only primary
   entity holder.

**Loop semantics:**

- Each app MUST be deployed standalone at least once, fully through the
  `Role Loop` inspect-fix-redeploy cycle.
- The loop continues — without asking the operator — until **all** of the
  following hold simultaneously:
  - every Acceptance Criterion in this document is checked off (`- [x]`);
  - `make test` is green with no skipped suites;
  - both Final Iteration apps deploy cleanly end-to-end.
- Whenever a fix in one app could plausibly regress the other, the agent
  restarts the cycle from `web-app-nextcloud`.
- The agent MUST NOT pause for operator input on issues that are covered
  by this document.

## Commit Policy

- The agent MUST NOT create **any** git commit during implementation or
  iteration. No partial commits, no checkpoint commits, no per-step commits,
  no half-migrated intermediate commits. The working tree evolves in place
  until the loop's termination condition (above) is met.
- Only when **all** of the following hold does the agent prepare commits:
  - every Acceptance Criterion in this document is checked off (`- [x]`);
  - `make test` is green with no skipped suites;
  - both Final Iteration apps deploy cleanly.
- At that point, the agent lands the whole atomic refactor as a single
  commit (or a tight, related sequence) and then instructs the operator to
  run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)).
  The agent MUST NOT push.
