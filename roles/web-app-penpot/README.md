# Penpot

## Description

Deploys [Penpot](https://penpot.app/), the open-source design and prototyping
platform (a self-hostable Figma alternative) for UI/UX design, real-time
collaboration, asset libraries, version history, and developer handoff — fully
integrated into the Infinito.Nexus ecosystem.

## Overview

The role brings up Penpot's containerized stack behind the standard
Infinito.Nexus reverse proxy and wires it into central identity, backup, and
dashboard infrastructure. It follows the per-role meta layout
([layout.md](../../docs/contributing/design/role/services/layout.md)) and is
modeled on [`web-app-openproject`](../web-app-openproject/) and
[`web-app-baserow`](../web-app-baserow/).

### Containers

| Service    | Image                  | Purpose                                                        |
|------------|------------------------|----------------------------------------------------------------|
| `frontend` | `penpotapp/frontend`   | Nginx + SPA; public HTTP surface, proxies to backend/exporter. |
| `backend`  | `penpotapp/backend`    | API, auth (OIDC/LDAP), persistence, asset storage.             |
| `exporter` | `penpotapp/exporter`   | Headless renderer for SVG/PDF/image export and dev handoff.    |
| `redis`    | `svc-db-redis` (role-local sidecar, service name `redis`) | Cache / pub-sub for real-time collaboration. |
| `postgres` | shared `svc-db-postgres` | Relational store.                                            |

The **exporter** is mandatory: it backs the export (SVG/PDF) and developer
handoff features.

## Features

- Design creation and editing, team collaboration with comments and live cursors.
- Shared asset libraries and components, version history.
- Export (SVG, PDF, images) and developer handoff (CSS/code) via the exporter.
- Real-time collaboration over WebSockets through the proxy.
- **Identity attributes:** the OIDC e-mail and name claims and the LDAP username, e-mail, full name and user query come from the platform `OIDC.ATTRIBUTES` and `LDAP.USER.ATTRIBUTES`; every realm user may sign in.
- **Shared platform team:** Penpot has no instance administrator, only roles per team, so the role groups map onto one team named after `ORGANIZATION` that the platform administrator owns: `administrator` members are team admins, `editor` members editors and `viewer` members viewers; a profile outside all three leaves the team the way Penpot's own leave does. [files/sql/rbac/reconcile.sql](./files/sql/rbac/reconcile.sql) runs in the database as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer; it creates the team once the administrator's profile exists and matches members by e-mail, so a member joins on the first run after their first sign-in.
- **Directory full names:** the same hook sets the full name of every Penpot profile whose e-mail the directory holds to the directory's name, because Penpot takes the name from OIDC or LDAP only when it registers the profile.

## Identity

`services.penpot.login.method.*` in [meta/services.yml](./meta/services.yml) drives the login flags in `PENPOT_FLAGS` ([vars/main.yml](./vars/main.yml)):

- **`sso`:** `enable-login-with-oidc` (the in-app "OpenID" entry to [`web-app-keycloak`](../web-app-keycloak/)) together with `enable-oidc-registration`, so a first OIDC login creates its Penpot profile while local self-registration stays closed.
- **`ldap`:** `enable-login-with-ldap`, the "LDAP" button on the login form that binds against [`svc-db-openldap`](../svc-db-openldap/). Under SSO it is off and LDAP accounts sign in through the Keycloak federation.
- **`native`:** `enable-login-with-password` or `disable-login-with-password`. Penpot keeps the email and password fields for the LDAP button, but without this flag no local password signs in. When it is on, `tasks/main.yml` bootstraps a local password for the `administrator` profile through the backend PREPL (`create-profile` for a fresh profile, `update-profile` when a federated login already created it). With only `ldap` on, the same `create-profile` runs with a throwaway password nobody knows, so the shared platform team has its owner at the first deploy and the LDAP sign-in, which finds its profile by e-mail, lands in that profile.
- **`registration`:** `enable-registration` or `disable-registration`, the local "Create an account" path. Penpot accepts a local sign-up only while `native` is on as well.

Penpot has no second factor and no passkey, so the role declares neither.

**Break-glass:** Penpot has no instance administrator, only team roles. While SSO is on, the backend PREPL (`enable-prepl-server`) that `tasks/01_administrator.yml` drives manages profiles from the CLI.

## Storage & scalability

- Assets are stored on the filesystem backend (`PENPOT_ASSETS_STORAGE_BACKEND=assets-fs`)
  on the backup-ready named volume `penpot_assets`, mounted into both `frontend`
  and `backend` at `/opt/data/assets`.
- The PostgreSQL database is backed up by the central backup roles; the asset
  volume is backup-ready by convention.
- **S3-compatible object storage (future):** Penpot supports an `assets-s3`
  backend (`PENPOT_STORAGE_ASSETS_FS_*` → `PENPOT_STORAGE_ASSETS_S3_*`). It is
  intentionally **not** implemented here; switching the backend and adding the
  S3 credentials to `meta/secrets.yml` is the documented upgrade path.

## Ports & networking

- Canonical domain: `penpot.design.{{ DOMAIN_PRIMARY }}`.
- Local proxy bind: `services.penpot.ports.local.http` (`8041`).
- Role network: `192.168.105.192/28`.

## Autonomous-implementation notes

Resolved by best judgement during the autonomous build (per the requirement's
Procedure); revisit at PR review:

- **Image tag** pinned to `2.5.4` for all three containers (single upstream tag).
- **Exporter `PENPOT_PUBLIC_URI`** is shared from the single role env file (the
  external HTTPS base URL). Penpot upstream also supports an internal
  `http://frontend:8080` value; the shared-env contract renders one file for all
  containers, which the upstream image tolerates.
- **CSP** allows `unsafe-inline`/`unsafe-eval` for `script-src-elem` and
  `blob:` workers/images, required by Penpot's SPA and worker-based renderer.
- **OIDC JVM CA trust (self-signed TLS only):** when `TLS_MODE == self_signed`,
  the backend command (in `templates/compose.yml.j2`) imports the internal CA
  into a writable `cacerts` copy and points the JVM at it via `JAVA_TOOL_OPTIONS`.
  The shared `with-ca-trust.sh` entrypoint covers the OS/NSS/env trust stores but
  not the JVM truststore, so without this Penpot's server-side OIDC
  token/userinfo calls to Keycloak fail with `PKIX path building failed`. The
  override is gated behind self-signed mode (it is a no-op in production, where
  real CA-signed certs are already trusted) and the CA path is hardcoded because
  the framework's CA-override re-serialises the command.
- **`disable-onboarding`** is in `PENPOT_FLAGS` so users land directly on the
  dashboard (sovereign install; also keeps the project/asset flows testable).
- **`disable-admin-console`** is in `PENPOT_FLAGS` because Penpot 2.19 enables
  the Admin Console by default and then expects a `penpot-admin-console`
  service plus `PENPOT_ADMIN_CONSOLE_URI`, which this role does not deploy.
  Without the flag `manage.py create-profile` fails with `admin console is not
  configured`.

## Testing

The Playwright suite is split per login surface **and persona** (the runner
globs every `*.js` under `files/playwright/`):

- `_shared.js` — env + login helpers (`penpotOidcLogin`, `penpotLdapLogin`,
  `penpotNativeLogin`, `penpotRegister`).
- `test-login-native.js` — administrator native (local password) login;
  skipped when `sso` is enabled (native login is disabled under OIDC).
- `test-login-oidc-admin.js` — OIDC via Keycloak, administrator.
- `test-login-oidc-biber.js` — OIDC via Keycloak, `biber` (non-admin RBAC).
- `test-login-ldap-admin.js` — OpenLDAP bind, administrator; runs with `ldap` on and `sso` off.
- `test-login-ldap-biber.js` — OpenLDAP bind, `biber` (non-admin RBAC); runs with `ldap` on and `sso` off.
- `test-login-methods.js` — with `sso` on, the login page shows the OpenID entry and only the password, LDAP and registration entries whose `LOGIN_METHOD_*_ENABLED` flag is on.
- `playwright.spec.js` — orchestrator: TLS baseline, project creation, image
  asset upload, and the `guest`/`biber`/`administrator` personas. The `biber` /
  `administrator` personas are declared blocked via `PERSONA_*_BLOCKED`
  (mirroring `web-app-taiga`): Penpot's in-app "OpenID" entry and SPA user-menu
  logout aren't driveable by the generic persona helper, so both users' real
  auth is exercised by the dedicated login companions above.

Login/project/asset scenarios gate on the relevant service via
`skipUnlessServiceEnabled`, so a deploy reports them `skipped` (not `failed`)
when that service is disabled. Validated live against a Penpot + Keycloak +
OpenLDAP deploy.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Penpot Official Website](https://penpot.app/)
- [Penpot Configuration Guide](https://help.penpot.app/technical-guide/configuration/)
- [Penpot Docker Guide](https://github.com/penpot/penpot/tree/main/docker)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/LCynSv3uxC6VYzimXE4CGx)
