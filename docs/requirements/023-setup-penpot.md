# 023 - Setup Penpot

## User Story

As a Infinito.Nexus platform operator, I want to provide a fully integrated, production-ready Penpot design and prototyping platform within the Infinito.Nexus ecosystem so that teams can create, collaborate on, and share design projects directly inside their sovereign Infinito.Nexus installation.

## Context

[Penpot](https://penpot.app/) is an open-source design and prototyping platform (a self-hostable Figma alternative). This requirement tracks a new `web-app-penpot` Ansible role that deploys Penpot's containerized stack and wires it into the Infinito.Nexus ecosystem (identity, reverse proxy, marketplace, backup).

The role MUST follow the standard role-meta layout described in [layout.md](../contributing/design/role/services/layout.md) (`meta/services.yml`, `meta/schema.yml`, `meta/volumes.yml`, `meta/variants.yml`, `meta/info.yml`, `meta/main.yml`). [web-app-openproject](../../roles/web-app-openproject/) is the closest structural model — it combines PostgreSQL, a Redis `cache` service, background workers, an internal proxy, Keycloak SSO and LDAP — and SHOULD be used as the primary reference; [web-app-taiga](../../roles/web-app-taiga/) and [web-app-confluence](../../roles/web-app-confluence/) are secondary references.

Penpot's upstream stack is **frontend + backend + exporter + PostgreSQL + Redis**. The exporter container is mandatory: it backs the export (SVG/PDF) and developer-handoff features required below.

## Acceptance Criteria

### Role & meta layout

- [x] A new role exists at `roles/web-app-penpot/` and follows the role-meta layout in [layout.md](../contributing/design/role/services/layout.md).
- [x] `meta/services.yml` declares every container service and a `lifecycle` key (starting tier `beta`).
- [x] `meta/schema.yml` defines the role's configurable variables.
- [x] `meta/volumes.yml` declares the role's named volumes.
- [x] `meta/variants.yml` declares the matrix-deploy variants (see **Variants** below).
- [x] `meta/info.yml` and `meta/main.yml` are present and valid.

### Compose stack

- [x] The stack includes a Penpot **frontend** container.
- [x] The stack includes a Penpot **backend** container.
- [x] The stack includes a Penpot **exporter** container (required for SVG/PDF export and developer handoff).
- [x] PostgreSQL is provided via `svc-db-postgres` (declared through the `postgres` service block, not a role-local database container).
- [x] Redis is provided via the `redis` service block in `meta/services.yml` (auto-emitted `svc-db-redis` sidecar; service name `redis`).
- [x] All container volumes, env vars, ports and healthchecks follow Infinito.Nexus conventions.

### Identity integration

- [x] OIDC login is available via `web-app-keycloak`, enabled through `PENPOT_FLAGS` (e.g. `enable-login-with-oidc`). _(verified live against a Penpot + Keycloak deploy.)_
- [x] LDAP login is available via `svc-db-openldap`, enabled through `PENPOT_FLAGS` (e.g. `enable-login-with-ldap`). _(verified live against a Penpot + OpenLDAP deploy.)_
- [x] Native local email/password login is **off** under OIDC (`disable-login-with-password` forces users through SSO) and **on** otherwise, derived from the `sso` service flag (variant-aware); when on, the role bootstraps a local password for the `administrator` profile via the backend PREPL (`enable-prepl-server`) in `tasks/main.yml`, and the bootstrap is skipped under OIDC.
- [x] Self-registration is **on** when OIDC is enabled (Penpot's OIDC JIT provisioning routes through the registration path) and **off** otherwise, derived from the `sso` service flag, rendering `enable-registration`/`disable-registration` in `PENPOT_FLAGS`.
- [x] OIDC and LDAP configuration is fully automated via Ansible (env vars / templated config), requiring no manual post-deploy steps.

### CSP & reverse proxy

- [x] The role generates a correct Nginx/CSP vhost using [csp_filters.py](../../plugins/filter/csp_filters.py) and the `nginx_vhost` logic (via `sys-stk-full` + `meta/server.yml` CSP flags).
- [x] The vhost configures WebSocket upgrade so real-time collaboration (live cursors, comments) works (handled by the shared proxy template).
- [x] The vhost supports HTTPS termination and routes to internal service names.

### Variants

- [x] `meta/variants.yml` defines an **all-on** variant pinning every dynamic services flag to `true`.
- [x] `meta/variants.yml` defines an **all-off** variant pinning every dynamic services flag to `false`.
- [x] `meta/variants.yml` defines an **LDAP-only** variant (`ldap` on, `sso`/OIDC off) per the convention in [web-app-openproject/meta/variants.yml](../../roles/web-app-openproject/meta/variants.yml).

### Playwright coverage

- [x] A per-role Playwright spec exists and gates authenticated scenarios via `skipUnlessServiceEnabled` per [006 - Service-gated Playwright tests](README.md#archive).
- [x] A **separate** OIDC login scenario and LDAP login scenario exist (not combined into one test body) per [018](018-playwright-ldap-coverage.md).
- [x] Both the canonical admin persona and the non-admin RBAC persona `biber` are exercised per [017](017-playwright-biber-rbac-coverage.md).
- [x] A native (local-password) admin login scenario exists (`test-login-native.js`), separate from the OIDC/LDAP companions, and is skipped when `sso` is enabled (native login disabled under OIDC).
- [x] A scenario verifies project creation.
- [x] A scenario verifies asset upload.

### Infinito.Nexus integration

- [x] A marketplace entry for "Penpot Design" is added and correctly categorized (auto-discovered `web-app` role with `meta/info.yml` + `galaxy_tags`).
- [x] The role declares menu tags: `design`, `penpot`, `prototyping`, `collaboration`, `ui-ux`, `figma-alternative`.
- [x] Desktop and mobile launcher URLs are generated automatically from the role's domain.
- [x] PostgreSQL data is backed up via the existing backup role(s).
- [x] The asset-storage volume is backed up via the existing backup role(s).

### Storage

- [x] A named volume is configured for asset storage (design files, images, fonts) and is backup-ready.
- [x] Volume mounts follow Infinito.Nexus conventions.
- [x] S3-compatible object storage is documented as a future option in the role README (not implemented).

### Definition of done

- [ ] Penpot deploys successfully with one command on a fresh host.
- [ ] The app is reachable at its generated canonical domain (`penpot.design.{{ DOMAIN_PRIMARY }}`, e.g. `penpot.design.infinito.nexus`).
- [x] `roles/web-app-penpot/README.md` documents the role's purpose, configuration, and the S3 future option.
- [ ] `make test` passes with the new role in place. _(Penpot-relevant lint + integration suites verified green on host; full in-container `make test` requires `make setup`/sudo not available in the sandbox.)_

## Procedure

The implementation of this requirement MUST be executed autonomously by the agent. The following rules apply for the entire run and are non-negotiable:

- [x] **Clarifying questions only at the start.** Any open question, ambiguity, or missing decision (e.g. Penpot image versions, exporter resource limits, `PENPOT_FLAGS` set, lifecycle starting tier, secrets source) MUST be raised once at the very beginning of the run, in a single batched round, BEFORE any file is changed. Ambiguities discovered mid-run MUST be resolved by the agent using its best judgement, recorded in the role's `README.md` or a code comment, and revisited only at PR review.
- [x] **Iteration loops.** The agent MUST follow the [Role Loop](../agents/action/iteration/role.md) for every change inside `roles/web-app-penpot/`, and the [Playwright Loop](../agents/action/iteration/playwright.md) for every change to the role's Playwright spec. The debug-locally step MUST NOT be skipped in favour of remote CI reruns.
- [x] **No `ask` prompts mid-run.** The agent MUST NOT trigger any tool call that routes through `permissions.ask` in [.claude/settings.json](../../.claude/settings.json) during implementation. Where a tool would otherwise route through `ask`, the agent MUST select an equivalent covered by `permissions.allow`, or rephrase the operation to fit the sandbox. The single permitted exception is the final commit.
- [x] **No interruptions.** Bug fixes, deploy failures, lint failures, `make test` failures, and healthcheck flaps MUST be resolved at their root inside this same iteration without prompting the operator. Workarounds, ad-hoc skips, retry-until-green loops, or "track in a follow-up" deferrals MUST NOT be used.
- [ ] **One commit at the end.** ALL changes (role, meta, Playwright spec, documentation, marketplace entry, and the ticked checkboxes in this document) MUST be combined into ONE commit, created only after every Acceptance Criterion above is checked off (`- [x]`) and `make test` is green. The agent MUST NOT push; the operator runs `git-sign-push` outside the sandbox per [CLAUDE.md](../../CLAUDE.md).

## See Also

- Upstream: [Penpot Official Website](https://penpot.app/)
- Docker setup: [Penpot Docker Guide](https://github.com/penpot/penpot/tree/main/docker) (note the mandatory `exporter` service)
- Requirements convention: [requirements.md](../contributing/requirements.md)
- Role-meta layout: [layout.md](../contributing/design/role/services/layout.md)
- Structural model: [web-app-openproject](../../roles/web-app-openproject/); secondary: [web-app-taiga](../../roles/web-app-taiga/), [web-app-confluence](../../roles/web-app-confluence/)
- [006 - Service-gated Playwright tests](README.md#archive)
- [017 - Playwright biber RBAC coverage](017-playwright-biber-rbac-coverage.md)
- [018 - Playwright LDAP authentication coverage](018-playwright-ldap-coverage.md)
