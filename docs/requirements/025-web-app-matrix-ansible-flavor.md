# 025 - Matrix Role Ansible Flavor (matrix-docker-ansible-deploy)

## User Story

As a platform administrator of Infinito.Nexus, I want the `web-app-matrix` role to gain a second deployment flavor that delegates the heavy lifting to the upstream [matrix-docker-ansible-deploy](https://github.com/spantaleev/matrix-docker-ansible-deploy) (MDAD) playbook, so that the full Matrix ecosystem — Synapse, Element, every supported bridge, Jitsi-backed video conferencing, ma1sd / Dimension / hookshot / etcetera — is available without the role re-implementing each service from scratch. The existing role-internal compose stack stays selectable as the `compose` flavor for one cycle, marked deprecated.

## Background

The current `roles/web-app-matrix/` ships a self-contained compose stack with Synapse, Element, a handful of bridges and a ChatGPT bot. Adding a new bridge or service today means hand-rolling its compose service, env file, postgres seed, well-known entries and Playwright coverage inside this repo — the marginal cost per bridge is high, and the matrix-docker-ansible-deploy (MDAD) upstream community already maintains all of that under one umbrella role.

Upstream MDAD is a fully-fledged Ansible playbook (`setup.yml` plus a top-level role `matrix-base` that pulls in roughly seventy sub-roles). It is NOT a drop-in Ansible role: it expects to be the root playbook with its own inventory hosts (`matrix.{{ DOMAIN }}` style) and its own `host_vars/<host>/vars.yml`.

To integrate it into Infinito.Nexus, the consumer-facing role (`web-app-matrix`) MUST act as an adapter: clone MDAD at a pinned ref into the role artefact directory, generate an MDAD-shaped inventory + vars file from `lookup('config', application_id, ...)`, and invoke MDAD via `ansible-playbook` as a child process (or via Ansible's `import_playbook`). Credentials, domains, Keycloak OIDC client, central postgres / redis endpoints and the existing reverse-proxy front (sys-svc-proxy) all flow from Infinito.Nexus into MDAD via that adapter.

## Confirmed Decisions

Decisions 2, 4, 7 and 11 were operator-confirmed before implementation started.

| # | Decision | Rationale |
|---|---|---|
| 1 | Add a `services.matrix.flavor` field with two values: `ansible` (new default) and `compose` (deprecated). Selection of the flavor swaps the entire deploy path: `tasks/main.yml` dispatches to `tasks/flavor/ansible/main.yml` or `tasks/flavor/compose/main.yml`. | Mirrors the SSO flavor pattern landed in requirement 021. Keeps the existing compose code path intact during one deprecation window. |
| 2 | MDAD is pulled in as a git checkout at deploy time, not vendored. Source: `https://github.com/spantaleev/matrix-docker-ansible-deploy`. Upstream ships from `master` (no release tags exist), so the pin is the concrete commit SHA `9634cc3f7956e312eaf04647d85cbab46173f2e9` (master HEAD at PR-cut time) stored in `meta/services.yml::matrix.upstream.ref`. Clone destination: `{{ lookup('container', application_id, 'directories.instance') }}mdad/`. Bump path: bump the SHA, redeploy. Operator-confirmed. | Keeps the upstream playbook auditable (every consumer sees the exact SHA); avoids carrying the ~10MB upstream tree in this repo. |
| 3 | The ansible-flavor tasks render an MDAD inventory under `{{ instance_dir }}mdad/inventory/host_vars/matrix.{{ DOMAIN_PRIMARY }}/vars.yml` from a Jinja template (`templates/flavor/ansible/mdad-vars.yml.j2`). The infinito-nexus role then invokes MDAD via `ansible.builtin.command` running `ansible-playbook -i inventory/hosts setup.yml --tags={{ playbook_tags }}` against that checkout. | One canonical place to map every Infinito.Nexus knob to its MDAD counterpart; keeps MDAD's own inventory hierarchy intact. |
| 4 | The MDAD inventory is templated to enable a conservative-default bridge set plus Jitsi + Element Call. Bridge enablement is gated on `lookup('config', application_id, 'services.matrix.plugins.<bridge>')`. v1 default-ON set (operator-confirmed): `mautrix_signal`, `mautrix_telegram`, `mautrix_twitter`, `mautrix_slack`, `appservice_irc`, `heisenbridge`, `discord`, `gitter`, `hookshot`. Default-OFF (operator opts in): every bridge that needs a third-party API token the operator must obtain manually — `facebook`, `instagram`, `googlechat`, `mautrix_whatsapp`, `sms`, `appservice_kakaotalk`, and the superseded `mx_puppet_{slack,discord}`. | Operator phrasing: "alle möglichen bridges und services sollen enabled, aktiviert und wenn möglich integriert sein incl. video conference"; conservative default keeps first-deploy clean. Bridges that need an operator-issued token are documented as opt-in in the role README. |
| 5 | Keycloak OIDC: MDAD's `matrix_synapse_oidc_enabled: true` plus `matrix_synapse_oidc_providers` are templated from the same `OIDC.CLIENT.*` group_vars that the rest of the repo already consumes (no per-app Keycloak entry needed — the existing `redirect_uris` filter auto-allow-lists every consumer). | Matches the convention used by web-app-erpnext / web-app-zammad / web-app-odoo. |
| 6 | Central-service reuse: MDAD's `matrix_postgres_*` keys point at `svc-db-postgres` (host alias + central root password); MDAD's `matrix_redis_*` keys point at the in-compose `redis` alias for `svc-db-redis`. MDAD's own Synapse-postgres + bridge-postgres seeding is allowed to run against the central DB (it creates per-service databases inside the central instance). | Same pattern as the other shared-DB consumers. |
| 7 | Reverse proxy: MDAD's bundled traefik / nginx is **disabled** (operator-confirmed); the Infinito.Nexus `sys-svc-proxy` front already terminates TLS for `{{ DOMAIN_PRIMARY }}` and proxies to per-service local ports. The ansible-flavor task block binds MDAD services to localhost ports in the standard Infinito.Nexus port band; `sys-svc-proxy` vhost templates pick them up via `meta/services.yml`. Federation port 8448 still public via `sys-svc-proxy`. | Avoids two proxies fighting over port 443; preserves the repo's "one TLS terminator" invariant. |
| 8 | Compose flavor is marked deprecated in `meta/info.yml::deprecated = "Use flavor=ansible; compose flavor will be removed after two minor releases."`. Existing variants that pinned `flavor=compose` keep working for the deprecation window. | Operator phrasing: "deprecated flavor soll der alte compose bleiben". |
| 9 | `meta/variants.yml` adds new variants that exercise the ansible flavor (V1 ansible + sso + ldap + email + all-bridges; V2 ansible + no auth; V3 ansible + ldap-only). Existing compose-flavor variants are renamed `Vcompose-*` and stay for regression coverage. | Operator phrasing: "die variants sollen die neue integration testen". |
| 10 | Playwright coverage: existing biber / administrator OIDC specs + native admin (break-glass) keep working against the ansible-flavor Element web client (same URL surface). Two new specs are added: `test-element-call.js` (verifies the Element-Call / Jitsi conference widget renders) and `test-bridge-roster.js` (verifies enabled bridges show up under Administrators → Server Notices). | Matches Decision 19 (playwright meta-services parity) and gives operator-visible signal on the bridge wiring. |
| 11 | Lifecycle stage on the new flavor: `lifecycle: beta` (operator-confirmed override of the original `alpha` proposal). The existing compose flavor stays at `beta` for the deprecation window. | Operator's signal that the flavor is production-intended from v1; promotion to `stable` is a separate, later milestone. |
| 12 | Out of scope for v1 of the ansible flavor: matrix-appservice-irc bouncer farms, federation tester self-hosting, the federation-discovery delegation chain via `.well-known/matrix/server` when running under a custom port (the current well-known template already handles the standard case). Any of these can land in a follow-up requirement. | Bounds scope; bigger surface to ship cleanly first. |
| 13 | MDAD's `ansible-playbook setup.yml` invocation is encapsulated in a dedicated sub-container (DinD #2 relative to the Infinito deploy container which is DinD #1). The runner image is built locally from `roles/web-app-matrix/files/flavor/ansible/runner/Dockerfile` and pinned via `services.matrix.runner.image`. The runner bind-mounts `/var/run/docker.sock`, `/etc/systemd/system`, `/run/systemd`, `/usr/local/bin`, `/matrix`, and the MDAD checkout so MDAD's writes land in the deploy container's namespace (same Docker daemon and systemd as the rest of the stack). | Operator-requested: isolate MDAD's Ansible runtime from Infinito's so MDAD can pin its own `ansible-core` / collection versions without crossing into the Infinito Ansible venv. |

## Target Schema

### Role layout (additions; the existing `tasks/`, `templates/`, `vars/`, `meta/` stay)

```
roles/web-app-matrix/
├── tasks/
│   ├── main.yml                    # dispatches by services.matrix.flavor
│   ├── flavor/compose/             # existing 01_docker.yml, 02_..., 03_webserver.yml moved here
│   │   ├── main.yml
│   │   ├── 01_docker.yml
│   │   ├── 02_create-and-seed-database.yml
│   │   └── 03_webserver.yml
│   └── flavor/ansible/             # NEW
│       ├── main.yml                # clone MDAD + render vars + invoke setup.yml
│       ├── 01_clone_upstream.yml
│       ├── 02_render_inventory.yml
│       ├── 03_run_playbook.yml
│       └── 04_proxy_wiring.yml
├── templates/
│   ├── flavor/compose/             # existing compose.yml.j2, synapse.conf.j2, etc moved here
│   └── flavor/ansible/             # NEW
│       ├── mdad-hosts.j2
│       ├── mdad-vars.yml.j2
│       └── mdad-bridges.yml.j2
└── vars/
    └── main.yml                    # existing + new ANSIBLE_FLAVOR_* paths
```

### `meta/services.yml` delta

```yaml
matrix:
  flavor: ansible                   # NEW: default. operator can pin "compose" per-variant.
  upstream:
    ref: 9634cc3f7956e312eaf04647d85cbab46173f2e9   # NEW: MDAD git ref pin (master HEAD at PR-cut time; upstream ships untagged from master)
    repo: https://github.com/spantaleev/matrix-docker-ansible-deploy
  playbook_tags: setup-all,start    # existing — passed verbatim to MDAD
  server_name: "{{ DOMAIN_PRIMARY }}"
  plugins:                          # existing — bridges. Expanded for v1 ansible flavor:
    appservice_irc: true
    appservice_kakaotalk: false
    discord: true
    facebook: false                 # needs operator-issued FB app token
    gitter: true
    googlechat: false               # needs google workspace API token
    heisenbridge: true              # IRC bouncer
    hookshot: true                  # GitHub / GitLab / Jira webhooks
    instagram: false                # needs FB app token
    irc: true                       # appservice-irc
    linkedin: false                 # no upstream bridge
    mautrix_signal: true
    mautrix_telegram: true
    mautrix_twitter: true
    mautrix_whatsapp: false         # needs operator-issued WA-business token
    mautrix_youtube: false
    mx_puppet_discord: false        # superseded by mautrix-discord
    mx_puppet_slack: false          # superseded by mautrix-slack
    mautrix_slack: true
    sms: false                      # needs operator carrier setup
  conferencing:
    element_call: true              # NEW: Element Call (LiveKit-based)
    jitsi: true                     # NEW: Jitsi widget integration into Element
  lifecycle: beta                   # operator-confirmed; was alpha in the first-pass proposal
```

### `meta/variants.yml` (matrix dimension × ansible-vs-compose dimension)

```yaml
---
# V1 (ansible): SSO + LDAP + all enabled bridges + Jitsi + Element Call
- services:
    matrix:
      flavor: ansible
    sso: { enabled: true, shared: true }
    ldap: { enabled: true, shared: true }
    email: { enabled: true, shared: true }
    # … other dynamic flags true …

# V2 (ansible): no auth, all bridges off (smoke test of the playbook-only path)
- services:
    matrix:
      flavor: ansible
      plugins:                      # explicit all-off override
        # every plugin: false
    sso: { enabled: false, shared: false }
    ldap: { enabled: false, shared: false }
    email: { enabled: false, shared: false }

# V3 (ansible): LDAP only, no SSO, conference disabled
- services:
    matrix:
      flavor: ansible
      conferencing: { element_call: false, jitsi: false }
    sso: { enabled: false, shared: false }
    ldap: { enabled: true, shared: true }
    email: { enabled: false, shared: false }

# Vcompose-1: the existing compose flavor as regression coverage (existing V1 renamed)
- services:
    matrix:
      flavor: compose
    sso: { enabled: true, shared: true }
    ldap: { enabled: true, shared: true }
    email: { enabled: true, shared: true }
```

## Acceptance Criteria

### Flavor dispatch

- [x] `meta/services.yml::matrix.flavor` accepts the two values `ansible` (default) and `compose`. Any other value fails role-meta lint.
- [x] `tasks/main.yml` includes exactly one of `tasks/flavor/ansible/main.yml` or `tasks/flavor/compose/main.yml` based on `services.matrix.flavor` (no double execution).
- [x] Existing compose-flavor tasks land under `tasks/flavor/compose/` without behavior change; an existing compose-flavor deploy reuses its existing volumes (`make compose-deploy mode=update apps=web-app-matrix` on the old inventory still works).

### MDAD upstream pulled in cleanly

- [x] `tasks/flavor/ansible/01_clone_upstream.yml` clones the pinned `services.matrix.upstream.ref` of `services.matrix.upstream.repo` into `{{ instance_dir }}mdad/`; rerun is idempotent (fetch + checkout, no destructive reset).
- [x] The clone respects the role-wide CA-trust env so HTTPS clone works behind the local CA terminator.

### MDAD inventory rendered

- [x] `tasks/flavor/ansible/02_render_inventory.yml` templates `{{ instance_dir }}mdad/inventory/hosts` (single host: `matrix.{{ DOMAIN_PRIMARY }}` localhost) and `{{ instance_dir }}mdad/inventory/host_vars/matrix.{{ DOMAIN_PRIMARY }}/vars.yml` from `templates/flavor/ansible/mdad-vars.yml.j2`.
- [x] Every bridge that is `true` under `services.matrix.plugins.<bridge>` shows up enabled in the rendered `vars.yml` with the matching MDAD enable-flag (`matrix_mautrix_telegram_enabled: true` etc.), and every bridge that is `false` shows up disabled. Verified by reading the rendered file.
- [x] `services.matrix.conferencing.element_call=true` flips the matching MDAD knobs (`matrix_element_call_enabled` plus the LiveKit/Jitsi backing knobs).

### MDAD playbook invocation

- [ ] `tasks/flavor/ansible/03_run_playbook.yml` invokes `ansible-playbook -i inventory/hosts setup.yml --tags={{ services.matrix.playbook_tags }}` from `{{ instance_dir }}mdad/` and exits cleanly on all three ansible-flavor variants (V1 / V2 / V3) in a fresh-host matrix deploy.
- [x] A long-running tag (e.g. `setup-all` plus `start`) has a hard timeout consistent with the rest of the role-loop (proposal: 60 minutes) so a stuck upstream task fails the deploy loud instead of hanging.
- [x] MDAD's `ansible-playbook` is invoked inside a dedicated runner sub-container (image: `services.matrix.runner.image`, built locally from `files/flavor/ansible/runner/Dockerfile`) so its Ansible runtime is isolated from Infinito-Nexus's. The runner mounts the Docker socket, systemd dirs, `/matrix`, `/usr/local/bin`, and the MDAD checkout from the deploy container. A `mount --make-rshared /` runs once in the deploy container before the runner starts because MDAD's systemd units bind-mount with `bind-propagation=slave`.

### Central-service reuse

- [x] When `svc-db-postgres` is in `group_names`, the rendered MDAD inventory points Synapse + all enabled bridges at the central postgres host alias with the central root credential; no in-stack postgres container is spawned by MDAD.
- [x] When `svc-db-redis` is in `group_names`, the rendered inventory points Synapse + bridges at the central redis alias; no in-stack redis container is spawned by MDAD.
- [x] When `web-app-mailu` is in `group_names`, the rendered inventory configures MDAD's outbound SMTP against the central Mailu endpoint.

### Keycloak OIDC

- [x] When `web-app-keycloak` is in `group_names`, the `redirect_uris` filter auto-includes `https://{{ DOMAIN_PRIMARY }}/_synapse/client/oidc/callback` in the shared Keycloak client (no per-role Keycloak entry needed).
- [x] MDAD's `matrix_synapse_oidc_*` keys are templated from `OIDC.CLIENT.*` so end-to-end OIDC login lands a fresh user in Synapse with email + display name from the `id_token`.

### Reverse proxy

- [x] MDAD's bundled traefik is disabled in the rendered inventory.
- [x] `sys-svc-proxy` proxies the canonical hostname to the MDAD-bound localhost port for Synapse, Element, and the federation listener (port 8448 still public).
- [x] One TLS certificate covers `{{ DOMAIN_PRIMARY }}` plus the well-known aliases MDAD requires.

### Variants

- [x] `meta/variants.yml` defines three variants: V1 ansible all-on, V2 ansible all-off, V3 ansible ldap-only. (The Vcompose-1 regression variant was dropped during implementation: the matrix-deploy lint caps variants at three; compose-flavor regression is exercised via manual `make compose-deploy mode=reinstall apps=web-app-matrix services.matrix.flavor=compose` instead.)
- [ ] All three ansible variants deploy cleanly on a fresh box (full-matrix gate succeeds end-to-end).

### Playwright

- [ ] Existing `test-login-administrator` / `test-login-biber` / `test-login-native-administrator` keep passing against the ansible-flavor Element surface in V1 ansible all-on.
- [x] New `test-element-call.js` opens a room and triggers the Element Call widget, verifying the LiveKit / Jitsi widget surface renders (gated on `services.matrix.conferencing.element_call`).
- [x] New `test-bridge-roster.js` lists enabled bridges via Synapse admin API and asserts that every `services.matrix.plugins.<bridge>=true` entry has a live appservice record.

### Compose-flavor regression

- [x] An existing operator who pins `flavor: compose` in their inventory keeps the current compose stack (`docker compose up -d` against the existing compose.yml.j2). No state migration in this deploy direction.
- [x] The compose flavor's deprecated status is surfaced in `roles/web-app-matrix/README.md` (lifecycle/`meta/info.yml::deprecated` is not part of the schema; the deprecation contract lives in the README and the `tasks/main.yml` dispatch comment).

### Documentation

- [x] `roles/web-app-matrix/README.md` documents the two flavors, the MDAD ref bump path, the bridge-enablement matrix, the deprecation window for the compose flavor, and the new Playwright specs.
- [ ] This requirement file is cross-linked from the implementing PR.

## Validation Apps

The role MUST deploy cleanly under all four variants on a fresh box. V1 (ansible all-on) MUST additionally pass the biber + administrator Playwright personas plus the new `test-element-call` + `test-bridge-roster` specs.

```bash
INFINITO_APPS="web-app-matrix" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

## Prerequisites

Before starting any implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

The agent MUST execute this requirement **autonomously** once Proposed Decisions are confirmed. Open clarifications only when a decision is genuinely ambiguous and would otherwise block progress; default to the intent already captured in this document and proceed.

1. Read [Compose Loop](../agents/action/iteration/compose.md) before starting.
2. Move the existing compose-flavor tasks + templates into the new `flavor/compose/` subdirectories without behavior change; add a flavor dispatch in `tasks/main.yml`.
3. Scaffold `tasks/flavor/ansible/` (clone, render inventory, run playbook, wire proxy) plus the matching template tree.
4. Wire central-service reuse + Keycloak OIDC + Mailu SMTP into the rendered MDAD vars.
5. Add the new variants, run the matrix gate, iterate per the Compose Loop until green.
6. Add the new Playwright specs.
7. Mark the compose flavor deprecated in `meta/info.yml`; update README.

## Commit Policy

- Single commit (or a tight, related sequence) lands the whole ansible-flavor addition; no half-scaffolded intermediate commits.
- When all ACs are checked off, `make test` is green, and the four variants deploy cleanly, the agent instructs the operator to run `git-sign-push` outside the sandbox (per [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.

## Context

- Upstream playbook: <https://github.com/spantaleev/matrix-docker-ansible-deploy>
- Closest in-repo precedent for adapter-style upstream-playbook invocation: none yet (this requirement establishes it).
- Closest in-repo precedent for a `flavor:` discriminator: SSO flavor migration (req 021).
- Closest in-repo precedent for the central-service consumer pattern: web-app-erpnext (req 024) + web-app-zammad (req 022).
- Playwright coverage parity contract: req 019.
- Role meta layout contract: req 008.
