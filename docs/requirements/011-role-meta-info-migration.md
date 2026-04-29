# 011 - Role `meta/info.yml` Migration

## User Story

As a contributor, I want every role's descriptive role-level metadata
(icon, upstream homepage, demo video, dashboard display flag, …) to live
in a project-owned `roles/<role>/meta/info.yml` instead of being buried
inside `meta/main.yml.galaxy_info`, so that the Ansible Galaxy slot only
holds Galaxy-spec fields and project-internal metadata is addressable
through a stable, materialised `applications.<role>.info.<…>` path.

## Dependencies

This requirement is a follow-up to and depends on
[008 — Role Meta Layout Refactoring](008-role-meta-layout.md) and
[010 — Role Meta `run_after` / `lifecycle` Migration](010-role-meta-runafter-lifecycle-migration.md).
Req-008 and req-010 MUST both be fully merged (every Acceptance
Criterion checked off) before this requirement is started; the per-role
`meta/<topic>.yml` file-root convention introduced by req-008 and the
"primary entity is the role-level metadata holder" precedent set by
req-010 are treated as given.

## Background

Today, several project-internal fields live nested inside
`meta/main.yml.galaxy_info` alongside Ansible-standard Galaxy metadata.
Galaxy publishers ignore unknown keys, so the project has historically
buried non-Galaxy metadata there as a workaround:

```yaml
# roles/web-app-nextcloud/meta/main.yml (today, post req-010)
galaxy_info:
  author: Kevin Veen-Birkenbach
  description: ...
  license: ...
  galaxy_tags: [...]
  issue_tracker_url: https://s.infinito.nexus/issues
  homepage: https://nextcloud.com/                 # NOT a Galaxy field
  video: https://youtu.be/3jcYJGQgenI?si=...        # NOT a Galaxy field
  logo:                                             # NOT a Galaxy field
    class: fa-solid fa-cloud
```

Three previously-buried fields — `run_after`, `lifecycle`, and the
already-stripped `license_url` / `repository` / `documentation` — were
moved out as part of req-010 (the first two) and the
`tests/lint/repository/test_role_meta_main_galaxy_schema.py` enforcement
sweep (the latter three).

The remaining non-Galaxy fields under `galaxy_info` are:

| Field        | Purpose                                                                                  | Today |
|--------------|------------------------------------------------------------------------------------------|-------|
| `logo`       | UI icon (FontAwesome `class`) for dashboards, login pages, etc.                          | 78 roles |
| `homepage`   | Upstream project URL (e.g. `https://nextcloud.com/`).                                    | 1 role  |
| `video`      | Upstream demo / overview video URL.                                                      | 1 role  |
| `display`    | Dashboard hide-flag. Default `true`; a role sets `false` to opt out of the apps grid.    | 0 roles (default-on; consumer reads it) |

These four fields share the same anti-pattern: they pollute the Galaxy
slot to ride on Galaxy's "ignore unknown keys" tolerance.

## Target Layout

All four fields move to a new project-owned `roles/<role>/meta/info.yml`
file. The file-root convention from req-008 applies: there is no
wrapping `info:` key — the file's content IS the value of
`applications.<role>.info`.

```yaml
# roles/web-app-nextcloud/meta/info.yml
logo:
  class: fa-solid fa-cloud
homepage: https://nextcloud.com/
video: https://youtu.be/3jcYJGQgenI?si=FDmoMSrAb9_WvviC
```

`meta/info.yml` is OPTIONAL — a role with none of the four fields does
not grow the file. When the file is absent, consumers MUST treat each
field as absent / default (matching the current behaviour of
`galaxy_info.get("display", True)`).

After the migration, `meta/main.yml.galaxy_info` retains only
Ansible-standard Galaxy fields. Per the lint test
`tests/lint/repository/test_role_meta_main_galaxy_schema.py` introduced
during req-010 follow-up, that lint MUST go green for every role once
this requirement is merged.

### Allowed `meta/info.yml` Fields

| Field         | Type   | Semantics                                                                                                                |
|---------------|--------|--------------------------------------------------------------------------------------------------------------------------|
| `logo`        | map    | UI icon descriptor. Today only `class:` (FontAwesome). Future fields (`source:`, `svg:`) MAY be added here.              |
| `homepage`    | string | Upstream project URL — the canonical landing page of the software the role deploys.                                      |
| `video`       | string | Upstream demo / overview video URL.                                                                                      |
| `display`     | bool   | Default `true`. `false` opts the role out of dashboards / cards / apps grids.                                            |

The lint MUST reject any other top-level key in `meta/info.yml` so the
file does not become a new dumping ground for arbitrary metadata.
Future additions go through an explicit allowlist update in the same
change set that introduces the new field.

## Materialised Tree and Consumer Path Rewrites

| Old path                                          | New path                                       |
|---------------------------------------------------|------------------------------------------------|
| `<meta/main.yml>.galaxy_info.logo`                | `applications.<role>.info.logo`                |
| `<meta/main.yml>.galaxy_info.logo.class`          | `applications.<role>.info.logo.class`          |
| `<meta/main.yml>.galaxy_info.homepage`            | `applications.<role>.info.homepage`            |
| `<meta/main.yml>.galaxy_info.video`               | `applications.<role>.info.video`               |
| `<meta/main.yml>.galaxy_info.display`             | `applications.<role>.info.display`             |

Cross-role consumers that today read `<role>/meta/main.yml` directly to
extract any of the four fields MUST be rewritten to look the value up
through the materialised path, or through a helper analogous to
`utils/roles/meta_lookup.py` (req-010).

**Known consumers** that must be updated:

- `roles/web-app-dashboard/lookup_plugins/docker_cards.py` — reads
  `meta_data.galaxy_info.{logo.class, display, description, galaxy_tags}`
  off-disk per role. The `logo.class` and `display` reads move to the
  new `meta/info.yml` location; `description` and `galaxy_tags` are
  Galaxy-spec fields and stay where they are.

If new consumers appear during migration, they MUST also be moved to
the new path and listed in the PR description.

## Acceptance Criteria

### File migration

- [ ] Every role that has a `logo:` field nested under
      `meta/main.yml.galaxy_info` has that block moved verbatim to
      `meta/info.yml.logo`.
- [ ] Every role that has a `homepage:` field nested under
      `meta/main.yml.galaxy_info` has that string moved verbatim to
      `meta/info.yml.homepage`.
- [ ] Every role that has a `video:` field nested under
      `meta/main.yml.galaxy_info` has that string moved verbatim to
      `meta/info.yml.video`.
- [ ] Any role that today carries a `display:` field nested under
      `meta/main.yml.galaxy_info` has that bool moved verbatim to
      `meta/info.yml.display`. (At time of writing, no role sets this
      explicitly — but the consumer reads it with a default — so the
      migration is the schema-locking step rather than a data move.)
- [ ] After migration, no `meta/main.yml.galaxy_info` block contains a
      `logo`, `homepage`, `video`, or `display` key.
- [ ] Roles with none of these four fields MUST NOT grow an empty
      `meta/info.yml` file. The file is optional.

### Schema rules

- [ ] `meta/info.yml`, when present, is a YAML mapping at the file
      root. There is NO wrapping `info:` key.
- [ ] Allowed top-level keys: `logo`, `homepage`, `video`, `display`.
      Any other key fails the lint.
- [ ] `logo`, when present, is a mapping with at least a `class:`
      string field. Other sub-keys MAY be added by future allowlist
      updates.
- [ ] `homepage` and `video`, when present, are non-empty strings.
- [ ] `display`, when present, is a bool.

### Loader

- [ ] `utils/cache/applications.py` loads `roles/<role>/meta/info.yml`
      and exposes its content at `applications.<role>.info`. The load
      is silent / empty when the file is absent.
- [ ] Variants from `meta/variants.yml` that override `info` deep-merge
      over the loaded payload, just as they do over `services` /
      `server` / `rbac` / `volumes` per req-008.

### Consumer rewrites

- [ ] `roles/web-app-dashboard/lookup_plugins/docker_cards.py` reads
      `applications.<role>.info.{logo,display}` (via the materialised
      tree or a helper) instead of `meta/main.yml.galaxy_info.{logo,display}`.
- [ ] A repository-wide `grep` for `galaxy_info\.(logo|homepage|video|display)`
      MUST return zero matches after the refactor (outside this
      requirement file and historical changelogs).
- [ ] No legacy fallback to `meta/main.yml.galaxy_info` is implemented
      for these four fields; the new path is the single source of
      truth.

### Tests

- [ ] A new lint test under `tests/lint/` (e.g.
      `test_role_meta_info.py`) MUST fail if any of the following
      conditions occur:
      - a `meta/info.yml` carries a top-level key matching the file
        basename (`info:` wrapper);
      - a `meta/info.yml` carries a top-level key not in the allowlist
        (`logo`, `homepage`, `video`, `display`);
      - `logo` is not a mapping with at least a `class:` string;
      - `homepage` or `video` is not a non-empty string;
      - `display` is not a bool;
      - any role's `meta/main.yml.galaxy_info` carries `logo`,
        `homepage`, `video`, or `display`.
- [ ] The existing
      `tests/lint/repository/test_role_meta_main_galaxy_schema.py`
      goes green for the previously-failing 78+ roles whose only
      remaining offence was `logo` (and the 1 role whose offence was
      `homepage`/`video`).
- [ ] Unit tests cover a hypothetical helper that resolves
      `applications.<role>.info.<field>` from a synthetic role tree
      (similar to `utils/roles/meta_lookup.py`'s tests under
      `tests/unit/utils/roles/test_meta_lookup.py`).

### Documentation

- [ ] `docs/contributing/design/services/` (or equivalent) documents
      the new `meta/info.yml` shape, its allowed fields, and the
      file-root convention.
- [ ] `roles/<role>/AGENTS.md` and `roles/<role>/README.md` files that
      mention the old `galaxy_info.{logo,homepage,video,display}`
      location are updated to point at `meta/info.yml`.

### Atomicity & validation

- [ ] The migration MUST land as a single atomic change set: file
      moves, loader update, consumer rewrites, lint test, helper
      (if any), and docs ship together so no intermediate commit
      leaves the tree in a half-migrated state.
- [ ] `make test` passes after the refactor with no skipped suites.
- [ ] Every file and role touched by this refactoring is also
      simplified and refactored where possible, following the
      principles in [principles.md](../contributing/design/principles.md).

## Validation Apps

The following selection covers all relevant migration patterns and MUST
deploy end to end after the refactor:

| App                  | Why it's in the validation set                                                              |
|----------------------|---------------------------------------------------------------------------------------------|
| `web-app-dashboard`  | The only consumer of `galaxy_info.logo` / `galaxy_info.display` today.                      |
| `web-app-nextcloud`  | The only role that carries `homepage` and `video` in addition to `logo`.                    |
| `web-app-gitea`      | Single-entity service role with `logo` set; baseline regression check.                      |
| `web-app-bluesky`    | Multi-entity role with `logo`; exercises the "primary entity vs. info file" distinction.    |

```bash
APPS="web-app-dashboard web-app-nextcloud web-app-gitea web-app-bluesky" \
  make deploy-fresh-purged-apps
```

## Migration Notes

- The migration is mechanical: read the four fields from each role's
  `meta/main.yml.galaxy_info`, write a `meta/info.yml` per role
  (file-root, no `info:` wrapper) when at least one of them is set,
  delete the originals from `galaxy_info`.
- For roles whose `meta/main.yml.galaxy_info` carries none of the four
  fields, the migration is a no-op — the role does NOT grow an empty
  `meta/info.yml`.
- Inline YAML comments next to the affected fields in `meta/main.yml`
  today (e.g. `homepage:` followed by an "Upstream homepage" comment)
  are NOT preserved by the mechanical migration. If a comment carries
  information worth keeping, the contributor MUST move it into the
  role's `README.md` or `AGENTS.md` before running the migration.
- This requirement does NOT touch `description`, `galaxy_tags`, or any
  other Galaxy-spec field. They stay under `galaxy_info` where they
  belong.

## Prerequisites

Before starting any implementation work, you MUST read [AGENTS.md](../../AGENTS.md)
and follow all instructions in it. You MUST also confirm that
requirements 008 and 010 are fully merged (every Acceptance Criterion
checked off); this requirement treats req-008's per-role
`meta/<topic>.yml` file-root convention and req-010's primary-entity
metadata-holder pattern as given.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open
clarifications only when a decision is genuinely ambiguous and would
otherwise block progress; default to the intent already captured in
this document and proceed.

1. Read [Role Loop](../agents/action/iteration/role.md) before
   starting.
2. Land the refactor in a single atomic branch:
   1. Update `utils/cache/applications.py` to load `meta/info.yml` →
      `applications.<role>.info` (file-root convention).
   2. Migrate `meta/main.yml.galaxy_info.{logo,homepage,video,display}`
      to `meta/info.yml.{logo,homepage,video,display}` across every
      affected role in one mechanical pass; create the file only when
      at least one of the four fields is set.
   3. Remove the now-empty `logo:` / `homepage:` / `video:` /
      `display:` keys from `meta/main.yml`.
   4. Rewrite `roles/web-app-dashboard/lookup_plugins/docker_cards.py`
      (and any other discovered consumer) to read from the new
      materialised path.
   5. Add the lint test that prevents the old location from coming
      back AND enforces the `meta/info.yml` allowlist.
   6. Update tests, fixtures, and docs.
3. Run `make test` until green.
4. Run the validation deploy listed above.

## Commit Policy

- The agent MUST NOT create **any** git commit during implementation.
  No partial commits, no checkpoint commits, no per-step commits, no
  half-migrated intermediate commits. The working tree evolves in
  place until both of the following hold:
  - every Acceptance Criterion in this document is checked off (`- [x]`);
  - `make test` is green with no skipped suites.
- At that point, the agent lands the whole atomic refactor as a single
  commit (or a tight, related sequence) and then instructs the
  operator to run `git-sign-push` outside the sandbox (per
  [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.
