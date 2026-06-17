# 026 - Dockerized `svc-net-wireguard` (consolidate core / plain / firewalled)

## User Story

As a platform administrator of Infinito.Nexus, I want a single Docker-based `svc-net-wireguard` role that runs WireGuard in a container (server **and** client modes) and replaces the three host-native roles `svc-net-wireguard-core`, `svc-net-wireguard-plain`, and `svc-net-wireguard-firewalled`, so that WireGuard is deployed the same containerized way as every other `svc-*` service, with one role to learn, one image to pin, and a reproducible multi-server end-to-end test instead of three host-coupled, distro-branching roles wired together by hand.

## Background

WireGuard currently ships as three separate host-native roles, all `wg-quick` / host-package based:

- `svc-net-wireguard-core` — installs `wireguard-tools` (Arch) / `wireguard` (Debian) on the host, drops a sysctl file for IPv4/IPv6 forwarding, copies a per-host `wg0.conf` from the inventory, restarts the host's WireGuard service. This is the **server**.
- `svc-net-wireguard-plain` — installs a systemd unit + `set-mtu.sh` that forces MTU 1400 on the internet interface(s). This is a **client** helper.
- `svc-net-wireguard-firewalled` — runs `iptables -A FORWARD -i wg0-client -j ACCEPT && iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE`. This is the **client-behind-NAT** helper.

The trio is host-coupled (writes `/etc/wireguard/`, `/etc/sysctl.d/`, host `iptables`), distro-branchy, and managed by hand through each role's `Administration.md`. Keys, peers and addressing are operator-maintained outside the role.

Every other service in the repo (`svc-db-postgres`, `svc-db-redis`, …) runs as a Docker Compose stack assembled from `sys-svc-compose` / `sys-svc-container` base templates, with `meta/services.yml`, `meta/schema.yml`, a pinned image, and a healthcheck. WireGuard is the outlier. The [linuxserver/wireguard](https://docs.linuxserver.io/images/docker-wireguard/) image already provides both server and client behaviour in one container — server mode is selected automatically when `PEERS` is set, and the image's [User / Group Identifiers](https://docs.linuxserver.io/images/docker-wireguard/#user-group-identifiers) (`PUID` / `PGID`) contract maps container file ownership onto a host user, which is exactly the volume-ownership model the rest of the repo already follows.

This requirement collapses the three roles into one Docker-based `roles/svc-net-wireguard/`, preserving the NAT/masquerade behaviour of the old `-firewalled` role verbatim, and adds a Docker-in-Docker end-to-end test that stands up at least three WireGuard servers and verifies peer connectivity between them — mirroring the orchestrator logic already prototyped in `roles/svc-net-wireguard/example.sh.example` (the svc-runner E2E pattern: env-gate → artefact-check → delegate to `local.sh` / `external.sh`).

## Confirmed Decisions

Decisions 1–4 were operator-confirmed before the first implementation pass; decision 5 was added in a follow-up clarification round.

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | The three host-native roles `svc-net-wireguard-core`, `svc-net-wireguard-plain`, `svc-net-wireguard-firewalled` are **deprecated and removed**. The new `roles/svc-net-wireguard/` fully replaces them. A grep over the repo confirms no inventory / `group_vars` / role-dependency outside the three roles themselves references them, so removal is self-contained. | Operator chose "deprecate + remove". Matches the "refactor **to** svc-net-wireguard" framing; avoids carrying a dead host-native path. |
| 2 | The unified role supports **both** WireGuard modes behind a `services.wireguard.mode` discriminator: `server` (image runs with `PEERS` set, generates peer configs) and `client` (joins an upstream peer). The old `-plain` (MTU) and `-firewalled` (NAT) client concerns fold into `mode: client`. | Operator chose "server + client". One role owns the whole WireGuard surface; the linuxserver image already does both. |
| 3 | The multi-server end-to-end test is implemented with **Docker Compose inside Docker-in-Docker** for v1. The orchestrator is structured so a Docker Swarm and a Kubernetes backend can be added later without rewriting the assertions. | Operator: "docker compose now, we might add docker swarm + kubernetes support later." Compose+DinD reuses the repo's existing `sys-svc-compose` / DinD tooling; lightest path. |
| 4 | The NAT/masquerade behaviour of the old `-firewalled` role is **kept as the current logic** — the same `iptables -A FORWARD -i wg0-client -j ACCEPT` + `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE` rules — now applied in the container/network context of the new role and gated by a flag (default consistent with the old behaviour). | Operator: "keep current logic." No behavioural change to NAT; only its host moves into the role's container path. |
| 5 | The DinD test grows a **full mesh across ALL nodes** — 3 servers (role image) + 3 client workstations on **CentOS, Debian and Manjaro** — where every one of the 6 nodes is peered directly to the other five. The test verifies they all communicate by asserting a WireGuard handshake on every link (5 peers per node) plus ICMP ping across every node pair. The existing 3-server stage (`local.sh` / `external.sh`) stays; the mesh stage (`mesh.sh`) runs the all-node mesh in the same DinD run. | Operator: "full mesh between all clients and all servers as well", clients on native distro images, ping+handshake, "preserve the DiD logic". |

### Derived design choices (agent judgement; revisit at PR review)

- **Image:** `lscr.io/linuxserver/wireguard`, pinned by tag in `meta/services.yml::wireguard.version` (bump-tag-then-redeploy path documented in the README). The role wraps the upstream image directly; no custom `Dockerfile.j2` unless a later AC forces one. The pinned tag is the linuxserver release current at PR-cut time.
- **Capabilities / sysctl:** container gets `cap_add: [NET_ADMIN]` (and `SYS_MODULE` only when host-module loading is required), `sysctls: { net.ipv4.conf.all.src_valid_mark: 1 }`, and publishes `${SERVERPORT}:51820/udp`. Mounts `/config` as a named volume and (optionally) `/lib/modules` read-only.
- **PUID / PGID:** templated from the role's run user per the linuxserver User/Group-Identifiers contract, so `/config` ownership matches the host.
- **Compose assembly:** `templates/compose.yml.j2` built from `sys-svc-compose/templates/base.yml.j2` + `sys-svc-container/templates/base.yml.j2`, matching the `svc-db-postgres` precedent.

## Target Schema

### Role layout (new `roles/svc-net-wireguard/`)

```
roles/svc-net-wireguard/
├── tasks/
│   ├── main.yml                 # dispatch by services.wireguard.mode (server|client)
│   ├── 01_server.yml            # compose up server stack (PEERS set)
│   └── 02_client.yml            # compose up client stack + MTU + NAT (old -plain/-firewalled logic)
├── templates/
│   ├── compose.yml.j2           # sys-svc-compose + sys-svc-container base
│   ├── env.j2                   # PUID/PGID/SERVERURL/SERVERPORT/PEERS/PEERDNS/INTERNAL_SUBNET/ALLOWEDIPS/TZ
│   └── ...                      # any client-side helper templates (MTU, NAT rules)
├── vars/
│   └── main.yml                 # application_id + container/volume/port names
├── meta/
│   ├── main.yml                 # galaxy_info (carry the wireguard/vpn/networking tags)
│   ├── services.yml             # image, version, lifecycle, ports, mem/cpu limits
│   └── schema.yml               # any generated credentials (keys) if applicable
├── templates/
│   └── test.env.j2              # test-e2e-cli discovery marker + env contract
├── files/test/                  # DinD E2E (run by test-e2e-cli)
│   ├── test.sh                  # orchestrator (entry point test-e2e-cli runs)
│   ├── local.sh                 # in-DinD: 3 server stacks up + healthy
│   ├── external.sh              # peer handshake / connectivity assertions across the 3 servers
│   └── mesh.sh                  # full mesh: 3 servers + 3 distro clients, all-pairs ping
├── README.md                    # both modes, image bump path, NAT flag, migration note from the old 3 roles
└── Administration.md            # client/peer key + config management (merged from the old roles)
```

`roles/svc-net-wireguard/example.sh.example` is replaced by the real `files/test/` harness above.

### `meta/services.yml` (shape)

```yaml
---
wireguard:
  enabled: true
  image: lscr.io/linuxserver/wireguard
  name: wireguard
  version: <pinned-linuxserver-tag>
  mode: server                    # server | client; overridable per variant
  nat: true                       # preserves old -firewalled FORWARD + MASQUERADE logic
  min_storage: 0GB
  lifecycle: alpha                # carry the old -core lifecycle tier forward
  cpus: "0.1"
  mem_reservation: "32m"
  mem_limit: "64m"
  pids_limit: 64
  ports:
    public:
      wireguard: 51820            # /udp
```

### Removed paths

```
roles/svc-net-wireguard-core/         # deleted
roles/svc-net-wireguard-plain/        # deleted
roles/svc-net-wireguard-firewalled/   # deleted
```

## Acceptance Criteria

### Unified role exists and is Docker-based

- [x] `roles/svc-net-wireguard/` exists and follows the role-meta layout (`meta/services.yml` with a `lifecycle` key, `meta/main.yml`, `vars/main.yml`, `tasks/main.yml`), matching the `svc-db-postgres` precedent.
- [x] The role runs WireGuard from the pinned `lscr.io/linuxserver/wireguard` image via a Compose stack assembled from `sys-svc-compose` / `sys-svc-container` base templates (no host `wg-quick` / host package install in the deploy path).
- [x] `templates/env.j2` sets `PUID` / `PGID` from the role's run user per the linuxserver [User/Group Identifiers](https://docs.linuxserver.io/images/docker-wireguard/#user-group-identifiers) contract. (Server-mode deploy succeeds in the fork CI run, so the image starts with these values.)
- [x] The container is granted `NET_ADMIN`, sets `net.ipv4.conf.all.src_valid_mark=1`, and publishes the configured UDP port to `51820/udp` (verified in `templates/compose.yml.j2`).

### Mode dispatch (server + client)

- [x] `services.wireguard.mode` accepts exactly `server` and `client`; any other value fails fast via an `assert` task in `tasks/01_core.yml` (adapted from the AC's "fails role-meta lint" intent — a runtime guard rather than a separate lint rule).
- [x] `tasks/main.yml` → `01_core.yml` includes exactly one of `tasks/02_server.yml` or `tasks/03_client.yml` based on `services.wireguard.mode` (mutually-exclusive `when`; no double execution).
- [x] In `server` mode, the container runs with `PEERS` set so the linuxserver image enters server mode and generates the configured peer configs under `/config`. Proven in the fork CI run: `local.sh` brings up `PEERS=1` servers and `external.sh` reads each `/config/peer1/peer1.conf` and completes a handshake.
- [ ] In `client` mode, the container joins the configured upstream peer; the MTU-1400 behaviour of the old `svc-net-wireguard-plain` role is preserved (interface MTU is 1400 after deploy). (Not exercised: CI deploys the role in `server` mode only.)

### NAT / firewalled behaviour preserved

- [ ] When NAT is enabled (`services.wireguard.nat: true`, default consistent with the old `-firewalled` role), the role applies the same logic as the old role: `iptables -A FORWARD -i wg0-client -j ACCEPT` and `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE`. Verified by reading the active rules after deploy.
- [ ] When NAT is disabled, those rules are absent and peer traffic is a pure tunnel (no masquerade). Verified by reading the active rules.

> **NAT is currently unverified.** The rules live in `tasks/03_client.yml`, gated `when: nat and not DOCKER_IN_CONTAINER`, and only run in `client` mode. CI deploys the role in `server` mode (so `03_client.yml` never runs) and on a container host (so the `not DOCKER_IN_CONTAINER` guard would skip the rules anyway). The e2e harness exercises peer/mesh connectivity, not host masquerade. Verifying NAT needs a `client`-mode deploy with `nat: true` on a non-container host, then asserting `iptables -t nat -S` contains the `POSTROUTING … MASQUERADE` rule (and a peer reaching the internet through it). See Validation Status.

### Old roles removed cleanly

- [x] `roles/svc-net-wireguard-core/`, `roles/svc-net-wireguard-plain/`, and `roles/svc-net-wireguard-firewalled/` are deleted.
- [x] A repo-wide grep for `svc-net-wireguard-core|svc-net-wireguard-plain|svc-net-wireguard-firewalled` returns no remaining references (only the generated, git-ignored `tasks/groups/svc-net-roles.yml`, which was regenerated and now lists only `svc-net-wireguard`). Dependency-resolution integration tests pass after removal.
- [x] `roles/svc-net-wireguard/README.md` documents the migration from the three old roles, including how the old `-core` server, `-plain` MTU, and `-firewalled` NAT behaviours map onto the new `mode` + `nat` settings.

### Multi-server Docker-in-Docker E2E test

- [x] `roles/svc-net-wireguard/files/test/` contains an orchestrator (`test.sh`) that mirrors the svc-runner test pattern: it env-gates required variables, verifies the backend, then delegates to `local.sh` and `external.sh`. The `example.sh.example` stub is removed. (Scripts are shellcheck-clean.)
- [x] `local.sh` brings up **at least three** independent WireGuard **server** instances inside Docker-in-Docker via Docker Compose (one server per instance) and enforces `WIREGUARD_E2E_SERVER_COUNT >= 3`. Proven in the fork CI run (`OK: all 3 WireGuard servers healthy`).
- [x] `external.sh` registers a peer on each server and asserts a successful WireGuard handshake against all servers, failing loudly (non-zero exit) if any is unreachable, bounded by `WIREGUARD_E2E_TIMEOUT`. Proven in the fork CI run (`OK: all 3 servers reachable via WireGuard handshake`).
- [x] The orchestrator is structured so the instance-provisioning backend is swappable via `WIREGUARD_E2E_BACKEND` (Compose today; Swarm / Kubernetes later) without changing `external.sh`. Documented in the `test.sh` header.

### Full mesh across all servers and clients

- [x] `files/test/mesh.sh` exists, is wired into `test.sh` (runs after `local.sh` / `external.sh`), and runs entirely in Docker-in-Docker alongside the 3-server stage (DinD logic preserved). (Shellcheck-clean.)
- [x] The mesh stands up **all six nodes**: 3 servers (the role's `lscr.io/linuxserver/wireguard` image) plus 3 client workstations on **CentOS, Debian, and Manjaro** from their native base images (overridable via `WIREGUARD_E2E_{CENTOS,DEBIAN,MANJARO}_IMAGE`). Each node installs/has `wireguard-tools` via its own package manager (`apt` / `dnf` / `pacman`).
- [x] All six nodes form a **full mesh**: each node's `wg0.conf` peers it directly to the other five (generated keypairs, per-peer `AllowedIPs`, container-name endpoints).
- [x] `mesh.sh` verifies **every node communicates with every other**: it asserts a WireGuard handshake on every link (each node shows 5 peer handshakes) and ICMP ping reachability across every node pair, failing non-zero (bounded by `WIREGUARD_E2E_TIMEOUT`) if any pair cannot reach the other. Proven in the fork CI run: all 30 directed pairs `reachable over tunnel`, every node `5/5 peer handshake(s)`, `full-mesh connectivity verified across all servers + clients (6 nodes)`.
- [x] CI discovers and runs the harness automatically (no manual step) via the `test-e2e-cli` role adopted from upstream ([infinito-nexus/core#231](https://github.com/infinito-nexus/core/pull/231)): it discovers any role shipping `templates/test.env.j2`, renders that env, and runs `files/test/test.sh` in the deploy container (Docker-in-Docker via the host socket). The wireguard role conforms by shipping `templates/test.env.j2` + `files/test/{test.sh,local.sh,external.sh,mesh.sh}`. `test-e2e-cli` is invoked post-deploy from `tasks/stages/02_{server,universal,workstation}.yml`, gated `RUNTIME in ['dev','act','github']`.

### Repo gate & docs

- [x] `make test` passes with the new role in place and the three old roles removed (all five targets green: lint, test-external, test-integration, test-lint, test-unit).
- [ ] The new role deploys cleanly in both `server` and `client` mode on a fresh box. (`server` mode proven in the fork CI universal deploy; `client` mode not yet exercised.)
- [ ] This requirement file is cross-linked from the implementing PR, and the implementing PR is cross-linked back here per [requirements.md](../contributing/requirements.md).

## Validation Status

Verified in the sandbox (no privileged Docker, no `sudo`):

- **Full `make test` is green** — all five targets pass (lint, test-external, test-integration,
  test-lint, test-unit), with the new role in place and the three old roles removed.
- Targeted integration suites pass against the new tree: `infrastructure/services`
  (`test_id_matches_role`, `test_canonical`, `test_resolvable`,
  `test_transitive_dependencies`, `test_mailu_dependency`),
  `infrastructure/docker/test_services_image_version_valid`,
  `infrastructure/networks` (unique/non-overlapping subnet + compose-role-has-local-network),
  `infrastructure/compose` (network-includes, compose_volumes-call, build-requires-image, no-raw-docker),
  and the full `infrastructure/` tree (32 tests).
- `tests/integration/roles/` structural tree (89 tests: includes, naming, run_once, when, meta) passes,
  after regenerating the git-ignored `tasks/groups/svc-net-roles.yml` (now lists only `svc-net-wireguard`).
- Targeted unit modules pass: `cli.meta.roles.test_lifecycle_filter`, `plugins.lookup.test_config_lookup`,
  `plugins.lookup.test_applications`, `cli.administration.inventory.validate.test_main`.
- `ansible-lint` (profile `min`) clean — the templated `path_join` include's expected `load-failure`
  is ignored in `.ansible-lint-ignore`, matching the `svc-db-openldap` precedent.
- `shellcheck` clean (via `make test`) on `files/test/{test.sh,local.sh,external.sh,mesh.sh}`.

Verified end-to-end in the fork CI (manual run, universal deploy, green):

- `server`-mode deploy of `svc-net-wireguard` succeeds; `test-e2e-cli` discovered and ran the harness.
- The DinD `files/test/test.sh` run passed fully: `local.sh` (3 servers healthy) → `external.sh`
  (3 peer handshakes) → `mesh.sh` (6-node full mesh, all 30 directed pairs reachable, 5/5 handshakes
  per node) → `ALL CHECKS PASSED`.

Still unverified:

- `client`-mode deploy (MTU-1400) — CI deploys `server` mode only.
- **NAT / firewalled rules** — `tasks/03_client.yml` runs only in `client` mode and is gated
  `not DOCKER_IN_CONTAINER`, so neither CI (server mode, container host) nor the e2e harness exercises
  it. Needs a `client`-mode deploy with `nat: true` on a non-container host plus an `iptables -t nat -S`
  assertion.

## Validation

```bash
# Role deploy (both modes) on a fresh box, then the DinD multi-server E2E:
INFINITO_APPS="svc-net-wireguard" make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
bash roles/svc-net-wireguard/files/test/test.sh
```

## Prerequisites

Before starting any implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it. Before modifying anything under `roles/svc-net-wireguard/`, the agent MUST check for `roles/svc-net-wireguard/AGENTS.md` and follow it if present.

## Implementation Strategy

The agent MUST execute this requirement **autonomously** once the Confirmed Decisions above stand. Open clarifications only when a decision is genuinely ambiguous and would otherwise block progress; otherwise default to the intent captured here and proceed.

1. Read [Role Loop](../agents/action/iteration/role.md) before starting.
2. Scaffold `roles/svc-net-wireguard/` as a Compose-based `svc-*` role (image pin, `env.j2`, `compose.yml.j2` from the shared bases, `meta/services.yml` + `meta/main.yml` + `vars/main.yml`).
3. Implement `mode: server` (PEERS, peer-config generation, caps/sysctl/port) and `mode: client` (upstream join + MTU-1400 from old `-plain`).
4. Port the old `-firewalled` NAT rules verbatim behind the `nat` flag.
5. Build the DinD E2E harness under `files/test/` (`test.sh` / `local.sh` / `external.sh` / `mesh.sh`) plus `templates/test.env.j2`, discovered by the adopted `test-e2e-cli` role; remove the stub.
6. Delete the three old roles and repoint / clean every remaining reference.
7. Run `make test` and iterate per the Role Loop until green.
8. Write `README.md` (both modes, image bump path, NAT flag, migration) and merge the old `Administration.md` guidance.

## Commit Policy

- A single commit (or a tight, related sequence) lands the whole role + test + old-role removal; no half-scaffolded intermediate commits.
- When all ACs are checked off and `make test` is green, the agent instructs the operator to run `git-sign-push` outside the sandbox per [CLAUDE.md](../../CLAUDE.md). The agent MUST NOT push.

## Context

- Upstream image: <https://docs.linuxserver.io/images/docker-wireguard/> (User/Group Identifiers: <https://docs.linuxserver.io/images/docker-wireguard/#user-group-identifiers>)
- Roles being consolidated: `svc-net-wireguard-core`, `svc-net-wireguard-plain`, `svc-net-wireguard-firewalled`.
- Test-orchestrator precedent: `roles/svc-net-wireguard/example.sh.example` (svc-runner E2E pattern; see req 014).
- Compose `svc-*` role precedent: `roles/svc-db-postgres/` (`compose.yml.j2` from `sys-svc-compose` / `sys-svc-container` bases).
- Closest precedent for a `mode:` / flavor discriminator collapsing roles into one: req 025 (Matrix flavor dispatch).
