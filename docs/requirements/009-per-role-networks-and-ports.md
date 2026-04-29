# 009 - Per-Role Networks and Ports Migration

## User Story

As a contributor, I want every role's IP subnet to live in that role's own
`meta/server.yml` and every port to live on the service entity that exposes
it inside `meta/services.yml`, so that adding a role does not require a
centralised registry edit, and so that two CLI helpers can suggest free ports
and free subnets by scanning the existing per-role layout.

## Dependencies

This requirement is a follow-up to and depends on
[008 — Role Meta Layout Refactoring](008-role-meta-layout.md). Req-008 MUST be
fully merged (every Acceptance Criterion checked off) before this requirement
is started; the per-role file shapes (`meta/server.yml` with `csp` / `domains`
/ `status_codes`, `meta/services.yml` keyed by `<entity_name>`) and their
materialised paths (`applications.<app>.server.<…>`, `applications.<app>.services.<entity>.<…>`)
are treated as given.

## Background

Today, two centralised files in `group_vars/all/` carry per-role network and
port assignments:

- [`group_vars/all/08_networks.yml`](../../group_vars/all/08_networks.yml) —
  `defaults_networks.local.<role>.subnet` per role plus `dns_resolver` (mailu),
  and global host-level keys (`NETWORK_IPV6_ENABLED`,
  `defaults_networks.internet.{ip4,ip6,dns}`).
- `group_vars/all/09_ports.yml` (since deleted by this requirement) —
  `ports.{localhost,public}.<category>.<role>` per role, with multi-entity
  roles flattened via `_<entity>` suffixes (`web-app-bluesky_api`,
  `web-app-matrix_synapse`, …).

In addition, many roles already carry a `port:` field directly on
`compose.services.<entity>` (e.g. `compose.services.gitea.port: 3000`,
`compose.services.listmonk.port: 9000`) that names the **internal container
port** of that entity. These intra-container ports today coexist with the
centralised `09_ports.yml` host-side ports.

This requirement consolidates all three sources into one per-entity shape and
moves the role-wide subnet into `meta/server.yml`.

## Target Layout

### Networks → `meta/server.yml.networks`

`networks:` is a new top-level section in each role's `meta/server.yml`. The
file-root convention from req-008 still applies (no wrapping `server:` key;
file content IS `applications.<app>.server`).

```yaml
# roles/<role>/meta/server.yml
# ... existing csp / domains / status_codes from req-008 ...
networks:
  local:
    subnet: 192.168.101.112/28        # required; CIDR of the role's docker network
    dns_resolver: 192.168.102.29      # optional, only when a fixed DNS resolver IP is needed (today: mailu)
```

The role's name is implied by the path — there is NO `web-app-<role>` key
inside the file.

### Ports → `meta/services.yml.<entity>.ports`

Ports belong to the service entity that exposes them. All port data lives
under `<entity>.ports` in `meta/services.yml` (no `ports:` section in
`meta/server.yml`).

```yaml
# roles/<role>/meta/services.yml
<entity>:
  image: ...
  version: ...
  ports:
    inter: <int>                      # internal container port
    local:
      <category>: <int>               # localhost-bound host port, keyed by band category
    public:
      <category>: <int>               # public-facing port, keyed by band category
      relay:                          # for port-ranges (coturn, BBB, nextcloud TURN)
        start: <int>
        end:   <int>
```

**Rules:**

- `ports.inter` is a **single int** when present. It is the renamed and
  int-cast successor of today's `compose.services.<entity>.port` field. If
  the source value is a quoted string (e.g. `port: "9090"`), the migration
  MUST cast it to int (`9090`).
- `ports.local` and `ports.public` are **always category-keyed maps**, even
  when the map has only one entry. Polymorphic int-or-map values are NOT
  supported. The category names are the same set as today's
  `09_ports.yml`: `http`, `database`, `websocket`, `oauth2`, `ldap`, `ssh`,
  `ldaps`, `stun_turn`, `stun_turn_tls`, `federation`, plus the structured
  `relay` block under `public:`.
- `ports.public.relay`, when present, is a map with the two integer keys
  `start` and `end` directly under `relay` (no nested entity-or-key sub-level),
  with `start < end`. Where today's `relay_port_ranges.<role>_start` / `_end`
  exist, they migrate to that single `relay: { start, end }` entry on the
  corresponding entity. Only one relay range per entity is supported.
- Existing nested port references that are NOT directly under the entity
  (e.g. `compose.services.<entity>.origin.port` for oauth2-proxy upstream,
  `compose.services.<entity>.metrics.port` for a metrics listener) are
  **out of scope** for this requirement and stay where they are. A follow-up
  may canonicalise them to look up `<upstream>.ports.inter`.

### Worked Examples

**Single-entity role (`web-app-gitea`, entity_name `gitea`):**

```yaml
# roles/web-app-gitea/meta/server.yml
networks:
  local:
    subnet: 192.168.101.112/28

# roles/web-app-gitea/meta/services.yml
gitea:
  image: gitea/gitea
  ports:
    inter: 3000           # was compose.services.gitea.port: 3000
    local:
      http: 8002          # was ports.localhost.http.web-app-gitea: 8002
    public:
      ssh: 2201           # was ports.public.ssh.web-app-gitea: 2201
```

**Multi-entity role (`web-app-bluesky`, entities `api`, `web`, `view`):**

```yaml
# roles/web-app-bluesky/meta/services.yml
api:
  ports:
    local: { http: 8030 }   # was ports.localhost.http.web-app-bluesky_api
web:
  ports:
    local: { http: 8031 }   # was ports.localhost.http.web-app-bluesky_web
view:
  ports:
    local: { http: 8051 }   # was ports.localhost.http.web-app-bluesky_view
```

**Role with co-located oauth2-proxy entity (`web-app-prometheus`):**

```yaml
# roles/web-app-prometheus/meta/services.yml
prometheus:
  image: prom/prometheus
  ports:
    inter: 9090             # was compose.services.prometheus's internal port
    local: { http: 8066 }
oauth2:
  enabled: true
  shared:  true
  ports:
    local: { oauth2: 16492 }   # was ports.localhost.oauth2.web-app-prometheus
```

**Port-range role (`web-svc-coturn`, entity `coturn`):**

```yaml
# roles/web-svc-coturn/meta/services.yml
coturn:
  ports:
    public:
      stun_turn:     3481
      stun_turn_tls: 5351
      relay:
        start: 20000
        end:   39999
```

**`dns_resolver` special case (`web-app-mailu`):**

```yaml
# roles/web-app-mailu/meta/server.yml
networks:
  local:
    subnet:       192.168.102.16/28
    dns_resolver: 192.168.102.29
```

**Role with `/24` non-`192.168.x.x` subnet and legacy fixed port
(`web-app-bigbluebutton`):**

```yaml
# roles/web-app-bigbluebutton/meta/server.yml
networks:
  local:
    subnet: 10.7.7.0/24                           # /24 = 254 clients

# roles/web-app-bigbluebutton/meta/services.yml
bigbluebutton:
  ports:
    local:
      http: 48087                                 # legacy BBB-fixed port; keep as-is during migration
    public:
      stun_turn:     3478
      stun_turn_tls: 5349
      relay:
        start: 40000
        end:   49999
```

## What stays in `group_vars/all/`

Per the operator's decision, these keys remain in
`group_vars/all/08_networks.yml` for now (out of scope for this requirement):

- `NETWORK_IPV6_ENABLED` — global IPv6 toggle.
- `defaults_networks.internet.{ip4, ip6, dns}` — host-level addresses.

Once every role has been migrated, the per-role `defaults_networks.local.*`
map and the entire `group_vars/all/09_ports.yml` file MUST be deleted.

## Port Bands

The per-category port ranges that the suggester proposes from and that the
lint check enforces are NOT hardcoded in CLI source. They live as a single
`PORT_BANDS` map in `group_vars/all/08_networks.yml` and are read by
`cli meta ports suggest` and the lint test at runtime.

**Every** category MUST have an entry. Protocol-fixed categories (`database`,
`ldap`, `ldaps`) get a tight band locked to their canonical port(s); the
suggester will correctly refuse new allocations there because the band is
already saturated, and the lint enforces that no role drifts off-band.

```yaml
# group_vars/all/08_networks.yml
PORT_BANDS:
  local:
    http:           { start: 8001,  end: 8099 }    # Web HTTP listener (fronted by nginx)
    websocket:      { start: 4001,  end: 4099 }    # Websocket listener
    oauth2:         { start: 16480, end: 16499 }   # oauth2-proxy callback
    database:       { start: 3306,  end: 5432 }    # Today: mariadb 3306, postgres 5432
    ldap:           { start: 389,   end: 389 }     # LDAP canonical (single port)
  public:
    ssh:            { start: 2201,  end: 2299 }    # SSH (git ops)
    stun_turn:      { start: 3478,  end: 3499 }    # STUN/TURN
    stun_turn_tls:  { start: 5349,  end: 5399 }    # STUN/TURN over TLS
    federation:     { start: 8448,  end: 8499 }    # Matrix federation
    ldaps:          { start: 636,   end: 636 }     # LDAPS canonical (single port)
    relay:          { start: 20000, end: 59999 }   # TURN relay ranges
```

The suggester exits non-zero when called for a `<scope>.<category>` that is
not in `PORT_BANDS`, unless the caller passes an explicit `--range`.

**Extensibility:** `PORT_BANDS` is intentionally extensible. When a future
role introduces a new category (e.g. `metrics`, `grpc`, …), the contributor
adds the corresponding `start`/`end` entry to `PORT_BANDS` in
`group_vars/all/08_networks.yml` *as part of the same change set* that
introduces the new port slot. The suggester and lint pick up new entries
automatically — there is no second registration step.

## Materialised Tree and Consumer Path Rewrites

| Old path                                                | New path                                                              |
|---------------------------------------------------------|-----------------------------------------------------------------------|
| `defaults_networks.local.<role>.subnet`                 | `applications.<role>.server.networks.local.subnet`                    |
| `defaults_networks.local.<role>.dns_resolver`           | `applications.<role>.server.networks.local.dns_resolver`              |
| `compose.services.<entity>.port` *(top-level on entity)*| `applications.<role>.services.<entity>.ports.inter`                   |
| `ports.localhost.<category>.<role>` *(single entity)*   | `applications.<role>.services.<entity>.ports.local.<category>`        |
| `ports.localhost.<category>.<role>_<entity>` *(multi)*  | `applications.<role>.services.<entity>.ports.local.<category>`        |
| `ports.public.<category>.<role>(_<entity>)?`            | `applications.<role>.services.<entity>.ports.public.<category>`       |
| `ports.public.relay_port_ranges.<role>_start`           | `applications.<role>.services.<entity>.ports.public.relay.start`      |
| `ports.public.relay_port_ranges.<role>_end`             | `applications.<role>.services.<entity>.ports.public.relay.end`        |

Every consumer of these old paths MUST be rewritten. Cross-role lookups that
read another role's network/port (e.g. resolving the mailu subnet from inside
nextcloud) MUST go through the same `lookup('config', '<other-role>', 'server.networks.local.subnet')`
or `lookup('config', '<other-role>', 'services.<entity>.ports.local.http')`
shape as any other meta path; no global registry remains.

## CLI Helpers

Two new commands under `cli/meta/`. Both walk the live role tree (`meta/server.yml`
for subnets, `meta/services.yml` for ports) and propose the next free slot.

### `cli meta ports suggest`

`inter` ports are NOT supported by the suggester — they are dictated by
upstream container images (`gitea=3000`, `postgres=5432`, …) and not
allocated from a project-managed pool. Inter ports are recorded in
`services.<entity>.ports.inter` directly by the contributor.

**Single-port categories** (everything except `relay`):

Inputs (CLI args):
- `--scope local | public` (required)
- `--category <name>` (required; e.g. `http`, `oauth2`, `ssh`, …)
- `--count N` (default 1) — how many free ports to return
- `--range <start>-<end>` (optional) — override the band from `PORT_BANDS`
  for ad-hoc allocations

Behaviour:
1. Read the band for `<scope>.<category>` from `PORT_BANDS` in
   `group_vars/all/08_networks.yml`. If absent and no `--range` is given,
   exit non-zero with a clear error.
2. Walk every `roles/*/meta/services.yml` and collect ints under
   `<entity>.ports.<scope>.<category>` (across ALL entities and ALL roles).
3. **Gap-first:** propose the lowest unoccupied port in the band.
4. **Increment fallback:** if the band has no gaps, propose `max(used) + 1`
   (clamped to the band's upper bound).
5. Exit non-zero if the requested count cannot be satisfied within the band.

Output: machine-readable list (one port per line) on stdout plus a
human-readable summary on stderr noting which band was used and how many
gaps were filled vs. appended.

**Range category `relay`:**

Inputs (CLI args):
- `--scope public --category relay` (required)
- `--length N` (required; the **inclusive port count** of the contiguous range,
  i.e. the span produced is `{start, end = start + N - 1}` — e.g.
  `--length 10000` yields a 10 000-port range like `20000–29999`).
- `--count K` (default 1) — how many independent free ranges to return

Behaviour:
1. Read the relay band from `PORT_BANDS.public.relay`.
2. Walk every `roles/*/meta/services.yml` and collect every
   `<entity>.ports.public.relay.{start,end}` pair as an occupied span.
3. **Gap-first:** propose the lowest unoccupied contiguous span of size
   `--length N` within the band.
4. **Increment fallback:** if no internal gap fits, propose
   `max(end) + 1` to `max(end) + N` (clamped to the band's upper bound).
5. Exit non-zero if `K` ranges of size `N` cannot be fit within the band.

Output: one `<start>-<end>` pair per line on stdout, summary on stderr.

### `cli meta networks suggest`

Inputs (CLI args):
- `--clients N` (required) — minimum number of usable client IPs
- `--count K` (default 1) — how many free subnets to return
- `--block <cidr>` (optional) — force suggestions inside a specific umbrella
  block (e.g. `--block 192.168.101.0/24`); default is the union of currently
  used /24 umbrella blocks for the chosen prefix length

Behaviour:
1. Translate `--clients N` to the smallest CIDR prefix that fits
   (≤14 → /28, ≤30 → /27, ≤62 → /26, ≤126 → /25, ≤254 → /24, …).
2. Walk every `roles/*/meta/server.yml` and collect occupied CIDRs from
   `networks.local.subnet`.
3. Within each umbrella /24 block already in use for the chosen prefix length:
   enumerate all sub-blocks of that prefix length, mark occupied vs. free.
4. **Gap-first:** propose the lowest unoccupied sub-block.
5. **Increment fallback:** if all sub-blocks of the active /24 blocks are
   used, propose the next /24 block in the established sequence
   (currently `192.168.101–105` for /28, `192.168.200–203` for /24).
6. **No established sequence:** if the requested prefix size has no umbrella
   block established yet (e.g. `--clients 1000` → `/22` and no `/22` is in
   use), exit non-zero with a clear error suggesting that the operator
   pass `--block <cidr>` to bootstrap a new umbrella block manually.
7. For each suggestion, also print the **client capacity**
   (`/28 → 14`, `/24 → 254`, …).

Output: one subnet per line, plus per-suggestion capacity on stderr.

### Integration with `cli create role`

When `cli create role` scaffolds a new role, it MUST:
- Prompt for `--clients N` and call `cli meta networks suggest --clients N --count 1`
  to fill in `meta/server.yml.networks.local.subnet` automatically.
- Prompt for required port categories per service entity and call
  `cli meta ports suggest --scope <…> --category <…> --count 1` per slot to
  fill in the entity's `ports` map.

The contributor MAY override either suggestion interactively.

## Acceptance Criteria

### File migration

- [ ] Every role that has an entry in `defaults_networks.local.*` of the old
      `group_vars/all/08_networks.yml` carries that subnet (and `dns_resolver`
      where present) in its own `meta/server.yml` under `networks.local`.
- [ ] Every role that has an entry in the old `group_vars/all/09_ports.yml`
      carries those ports in its own `meta/services.yml` under
      `<entity>.ports.{local,public}.<category>`.
- [ ] Every existing top-level `port:` field on a `compose.services.<entity>`
      block (post-req-008: `services.<entity>.port`) is renamed to
      `services.<entity>.ports.inter` and cast to int. String values
      (e.g. `port: "9090"`) become integers (`9090`).
- [ ] All multi-entity port entries (`<role>_<entity>: <int>` in the old file)
      are migrated to the entity-keyed shape under the matching entity in
      `meta/services.yml` (e.g. `web-app-bluesky_api: 8030` →
      `services.api.ports.local.http: 8030` inside
      `roles/web-app-bluesky/meta/services.yml`).
- [ ] All `relay_port_ranges.<role>_<start|end>` entries are migrated to
      `services.<entity>.ports.public.relay.{start, end}` on the corresponding
      entity.
- [ ] After migration, `group_vars/all/09_ports.yml` is deleted and
      `defaults_networks.local.*` is removed from `group_vars/all/08_networks.yml`.
      `NETWORK_IPV6_ENABLED` and `defaults_networks.internet.*` remain in
      `group_vars/all/08_networks.yml` (out of scope).

### Schema rules

- [ ] `meta/server.yml.networks.local.subnet` is a single CIDR string (no
      wrapping role-name key). Only `dns_resolver` is supported as an optional
      sibling of `subnet` under `networks.local`.
- [ ] `meta/services.yml.<entity>.ports.inter`, when present, is a single
      integer. Quoted strings are not allowed.
- [ ] `meta/services.yml.<entity>.ports.local` and `…ports.public` are
      **always** category-keyed maps (`{ <category>: <int>, … }`), even when
      the map has only one entry. Polymorphic int-or-map values are NOT
      supported. The lint guard MUST fail any role that uses a bare int.
- [ ] `meta/services.yml.<entity>.ports.public.relay`, when present, is a
      map with the keys `start` and `end`, both integers, with `start < end`.

### Consumer rewrites

- [ ] Every consumer (Python lookup plugin, Jinja template, `vars/*.yml`,
      task file) that reads
      `defaults_networks.local.<role>.{subnet,dns_resolver}`,
      `ports.localhost.<category>.<role>(_<entity>)?`,
      `ports.public.<category>.<role>(_<entity>)?`,
      `ports.public.relay_port_ranges.<role>_<start|end>`,
      or the old top-level `compose.services.<entity>.port`
      is rewritten to the equivalent
      `applications.<role>.{server.networks.local.<…>, services.<entity>.ports.<…>}`
      path.
- [ ] A repository-wide `grep` for `defaults_networks.local`,
      `ports.localhost.`, `ports.public.`, `relay_port_ranges.`, and the
      bare key `\.port:\s` directly under a `services.<entity>:` block MUST
      return zero matches outside of (a) this requirement file and (b)
      historical changelogs.
- [ ] No legacy fallback to the old paths is implemented.

### CLI helpers

- [ ] `cli meta ports suggest` exists with the inputs and behaviour described
      in "CLI Helpers" above. It scans `roles/*/meta/services.yml` for occupied
      ports across all entities and proposes free ports gap-first, then by
      increment, within the band looked up from
      `PORT_BANDS.<scope>.<category>` in `group_vars/all/08_networks.yml`.
- [ ] `--scope inter` is NOT a supported option for the ports suggester.
- [ ] When called for a `<scope>.<category>` not present in `PORT_BANDS` and
      without `--range`, the helper exits non-zero with a clear error listing
      the available categories.
- [ ] `cli meta ports suggest --scope public --category relay --length N`
      proposes contiguous free ranges of size `N` within the
      `PORT_BANDS.public.relay` band, gap-first then by increment.
- [ ] `cli meta networks suggest` exists with the inputs and behaviour
      described in "CLI Helpers" above. It scans `roles/*/meta/server.yml`
      for occupied subnets, picks the smallest CIDR prefix that fits the
      requested client count, and proposes free subnets gap-first, then by
      increment within the established umbrella blocks.
- [ ] `cli create role` invokes both helpers when scaffolding a new role and
      pre-fills `meta/server.yml.networks.local.subnet` and the requested
      port slots from the suggestions.
- [ ] Both helpers are deterministic: given the same on-disk role layout and
      the same arguments, they produce identical output.
- [ ] Both helpers exit non-zero with a clear error when the requested
      capacity cannot be satisfied within the configured band.

### Tests

- [ ] Unit tests cover both helpers' gap-first / increment-fallback behaviour
      against synthetic role-tree fixtures (occupied set, gap in band, no gap
      → next umbrella block, capacity overflow → non-zero exit).
- [ ] Unit tests cover the multi-entity port migration (`<role>_<entity>` →
      entity-keyed map under `meta/services.yml`) for at least one role of
      each pattern: bluesky (3 entities), matrix (2 entities), minio
      (2 entities), bigbluebutton (special port 48087).
- [ ] Unit tests cover the `port: <…>` → `ports.inter: <int>` rename + cast,
      including a string-value source (e.g. prometheus's `port: "9090"`).
- [ ] An integration test asserts that for every existing role, the
      materialised `applications.<role>.server.networks.local.subnet` and
      `applications.<role>.services.<entity>.ports.<…>` resolve to the same
      values as the pre-migration centralised files.
- [ ] A new lint test under `tests/lint/` MUST fail if any of the following
      conditions occur:
      - a role's `meta/services.yml.<entity>.ports.{local,public}` uses a
        bare int instead of a category-keyed map;
      - any role's `subnet` overlaps another's;
      - a `port:` key appears as a **direct child** of an `<entity>:` block in
        `meta/services.yml` (i.e. `<entity>.port`). Nested occurrences such
        as `<entity>.metrics.port` or `<entity>.origin.port` MUST NOT be
        flagged — those are intentionally out of scope per the "Migration
        Notes" below;
      - any host-bound port value collides with another host-bound port value
        across all roles. The collision check builds the **flat set of all
        host-bound ports** by combining:
        - every `services.<entity>.ports.local.<category>` int,
        - every `services.<entity>.ports.public.<category>` int (single-int
          categories),
        - and every integer in the inclusive range
          `[services.<entity>.ports.public.relay.start ..
          services.<entity>.ports.public.relay.end]`.

        It then fails if any value in that set appears in more than one slot
        (regardless of scope, category, role, or entity). This catches
        OS-level binding conflicts between e.g.
        `roleA.local.http: 8002` and `roleB.local.websocket: 8002`,
        and between a single port like `roleC.public.federation: 25000` and a
        relay span like `roleD.public.relay: { start: 20000, end: 29999 }`;
      - **`inter` values are NEVER part of any collision check.** Internal
        container ports live in per-container network namespaces; multiple
        roles may legitimately declare the same `inter` port (e.g. several
        nginx-based apps with `inter: 80`). The lint MUST explicitly skip
        `inter` for all collision rules above;
      - a `services.<entity>.ports.public.relay` range falls outside
        `PORT_BANDS.public.relay`, has `start >= end`, or has any sub-range
        that overlaps another role's relay range (subsumed by the
        flat-set rule above but called out for clarity);
      - a port value falls outside its `PORT_BANDS.<scope>.<category>` range,
        with the documented exception that
        `web-app-bigbluebutton.bigbluebutton.ports.local.http: 48087` (legacy
        BBB-fixed port) MUST be allow-listed by name in the lint. `PORT_BANDS`
        covers every category in use today (including the protocol-fixed
        `database`, `ldap`, `ldaps`); there are no "no band defined" cases to
        skip.

### Documentation

- [ ] `docs/contributing/design/services/` documents the new per-role
      `networks:` shape (in `meta/server.yml`) and the per-entity `ports`
      shape (in `meta/services.yml`), including the always-category-keyed
      rule and the `inter` / `local` / `public` split.
- [ ] `docs/contributing/tools/` (or equivalent) documents the two new CLI
      helpers with examples (`cli meta ports suggest --scope local --category http --count 3`,
      `cli meta networks suggest --clients 14 --count 2`).
- [ ] `cli create role`'s usage docs mention the auto-suggestion flow and
      how to override.
- [ ] `group_vars/all/08_networks.yml` retains a short header comment
      explaining what stayed (host-level + IPv6 toggle, plus the new
      `PORT_BANDS` map) and pointing at this requirement for what moved.
- [ ] `group_vars/all/08_networks.yml` carries the `PORT_BANDS` map exactly
      as defined in the "Port Bands" section above.

### Atomicity & validation

- [ ] The migration MUST land as a single atomic change set: file moves,
      consumer rewrites, CLI helpers, tests, and docs ship together so no
      intermediate commit leaves the tree in a half-migrated state.
- [ ] `make test` passes after the refactor with no skipped suites.
- [ ] Every file and role touched by this refactoring is also simplified
      and refactored where possible, following the principles in
      [principles.md](../contributing/design/principles.md).

## Validation Apps

The following selection covers all relevant migration patterns and MUST deploy
end to end after the refactor:

| App                       | Why it's in the validation set                                                                    |
|---------------------------|---------------------------------------------------------------------------------------------------|
| `web-app-gitea`           | Single-entity baseline (`inter`, `local.http`, `public.ssh`).                                     |
| `web-app-mailu`           | `dns_resolver` special case in `networks.local`.                                                  |
| `web-app-bluesky`         | 3-entity HTTP fan-out (`api`, `web`, `view`).                                                     |
| `web-app-matrix`          | 2-entity HTTP + `public.federation`.                                                              |
| `web-app-minio`           | 2-entity HTTP fan-out (`api`, `console`).                                                         |
| `web-app-bigbluebutton`   | `/24` non-`192.168.x.x` subnet + legacy fixed port `48087` + `public.relay`.                      |
| `web-svc-coturn`          | `public.relay` migration (`coturn_start`/`coturn_end` → `relay.{start,end}`).                     |
| `web-app-nextcloud`       | `public.relay` + cross-role network lookups (mailu, keycloak).                                    |
| `web-app-prometheus`      | `inter` rename from quoted `port: "9090"` + co-located oauth2 entity in `local.oauth2`.           |
| `web-app-listmonk`        | `inter` rename from `compose.services.listmonk.port: 9000` + `local.http`.                        |
| `svc-db-postgres`         | `/24` shared DB subnet + `local.database`.                                                        |
| `svc-db-mariadb`          | `/24` shared DB subnet + `local.database`.                                                        |
| `svc-db-openldap`         | `/24` shared LDAP subnet + `local.ldap` + `public.ldaps`.                                         |

```bash
APPS="web-app-gitea web-app-mailu web-app-bluesky web-app-matrix web-app-minio web-app-bigbluebutton web-svc-coturn web-app-nextcloud web-app-prometheus web-app-listmonk svc-db-postgres svc-db-mariadb svc-db-openldap" \
  make deploy-fresh-purged-apps
```

## Migration Notes

- The old `web-app-<role>_<entity>` flattened key shape carries an implicit
  separator (`_`) that conflicts with role names containing underscores
  (none today, but the schema lock-in is fragile). The new entity-keyed map
  removes that ambiguity by addressing the entity directly.
- `relay` is the new canonical name for the old `relay_port_ranges` block
  (rename: shorter, no implied "ranges-of-ranges").
- The mailu subnet's `dns_resolver` field is the only optional structured
  attribute under `networks.local` today. Keep it as a sibling of `subnet`,
  not under a different parent.
- Nested port references that are NOT directly under the entity
  (e.g. `services.<entity>.origin.port` for oauth2-proxy upstream,
  `services.<entity>.metrics.port` for metrics listeners) are intentionally
  out of scope for this requirement. They stay where they are; a follow-up
  may canonicalise them to look up the upstream entity's `ports.inter`.

## Prerequisites

Before starting any implementation work, you MUST read [AGENTS.md](../../AGENTS.md)
and follow all instructions in it. You MUST also confirm that requirement 008
is fully merged (every Acceptance Criterion checked off); this requirement
treats req-008's `meta/server.yml` and `meta/services.yml` shapes as given.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open clarifications
only when a decision is genuinely ambiguous and would otherwise block progress;
default to the intent already captured in this document and proceed. Avoid
back-and-forth questions on choices that are already specified above (file
location, port-shape (always category-keyed map), CLI helper placement,
`port:` rename and int-cast, what stays in `group_vars/all/`).

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Land the refactor in a single atomic branch:
   1. Build the two CLI helpers (`cli meta ports suggest`,
      `cli meta networks suggest`) plus their unit tests against synthetic
      fixtures.
   2. Migrate `group_vars/all/08_networks.yml` and `group_vars/all/09_ports.yml`
      content into per-role `meta/server.yml` (networks) and `meta/services.yml`
      (ports). Use the helpers to validate that no port collision and no
      subnet overlap is introduced.
   3. Rename and int-cast every existing top-level `services.<entity>.port`
      field to `services.<entity>.ports.inter`.
   4. Rewrite all consumers (lookup plugins, Jinja templates, `vars/*.yml`,
      task files) to read `applications.<role>.{server.networks.<…>,services.<entity>.ports.<…>}`
      paths.
   5. Delete `group_vars/all/09_ports.yml` and the `defaults_networks.local.*`
      block from `group_vars/all/08_networks.yml`.
   6. Wire the helpers into `cli create role`.
   7. Update tests, fixtures, and docs.
3. Run `make test` until green.
4. Run the validation deploy listed above.

## Final Iteration

After the changes are implemented in the working tree and an initial
`make test` run completes, the agent MUST iterate **autonomously** end-to-end
following [Role Loop](../agents/action/iteration/role.md) against the
following three apps (in order):

1. `web-app-bigbluebutton` — most port-edge cases (legacy fixed port, `/24`,
   `public.relay`, multiple `public.*` categories).
2. `web-app-bluesky`       — multi-entity HTTP fan-out + entity-keyed port map.
3. `web-app-gitea`         — minimal-shape baseline regression check
   (`inter`, `local.http`, `public.ssh` all present).

**Loop semantics:**

- Each app MUST be deployed standalone at least once, fully through the
  `Role Loop` inspect-fix-redeploy cycle.
- The loop continues — without asking the operator — until **all** of the
  following hold simultaneously:
  - every Acceptance Criterion in this document is checked off (`- [x]`);
  - `make test` is green with no skipped suites;
  - all three Final Iteration apps deploy cleanly end-to-end.
- Whenever a fix in one app could plausibly regress another, the agent
  restarts the cycle from `web-app-bigbluebutton`.
- The agent MUST NOT pause for operator input on issues that are covered by
  this document (layout, schema, lint rules, CLI helpers, etc.). It only
  surfaces a question when something is genuinely ambiguous and not
  derivable from the spec.

## Commit Policy

- The agent MUST NOT create **any** git commit during implementation or
  iteration. No partial commits, no checkpoint commits, no
  per-step commits, no half-migrated intermediate commits. The working tree
  evolves in place until the loop's termination condition (above) is met.
- Only when **all** of the following hold does the agent prepare commits:
  - every Acceptance Criterion in this document is checked off (`- [x]`);
  - `make test` is green with no skipped suites;
  - the three Final Iteration apps deploy cleanly.
- At that point, the agent lands the whole atomic refactor as a single
  commit (or a tight, related sequence) and then instructs the operator to
  run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)).
  The agent MUST NOT push.
