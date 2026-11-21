# BigBlueButton

## Description

This Ansible role deploys [BigBlueButton](https://bigbluebutton.org/) using Docker Compose. It includes support for Greenlight, OIDC, TURN/STUN, health checks, and a modular `.env` setup. This role is ideal for educational institutions and teams requiring a self-hosted video conferencing solution.
> 🔧 **Note**: The database layer should be decoupled in a future release to improve modularity and integration.
>

## Overview

This role provides a fully automated deployment of [BigBlueButton](https://bigbluebutton.org/) using Docker Compose on Arch Linux. It manages the entire lifecycle of the deployment, from cloning the upstream Docker repository and generating the `.env` configuration to customizing `compose.yml` for volume usage, WebSocket proxying, and optional OIDC integration.
The setup includes conditional Greenlight activation, WebRTC support via TURN/STUN, and various fixes for known container orchestration issues. The role is modular and integrates seamlessly with the Infinito.Nexus infrastructure, including reverse proxy configuration, domain management, and secrets templating.
By default, BigBlueButton is deployed with best-practice hardening, modular secrets, and support for multiple authentication methods and scalable storage backends.

## Features

- 🐳 **Docker-based** deployment via official [bigbluebutton/docker](https://github.com/bigbluebutton/docker)
- ✅ **Greenlight** (v3) frontend support
- 🔐 **SSO with OIDC** (optional). Greenlight v3 has no LDAP login, so directory users sign in through Keycloak's LDAP federation.
- **Administrator role:** [files/ruby/greenlight/reconcile_roles.rb](./files/ruby/greenlight/reconcile_roles.rb) sets the Greenlight `Administrator` role from the `web-app-bigbluebutton` `administrator` members, matched by email, and demotes every other Greenlight administrator to `User`, as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. The platform administrator keeps the role.
- 🧱 Automatic `.env` templating and domain/NGINX integration
- 🛠 Volume patching and Docker Compose customization
- 📬 SMTP integration and Greenlight admin creation: the administrator is verified and active, and its password converges on every deploy
- 🎨 Corporate design for Greenlight: brand color and logo through the Greenlight site settings, the configured title through the design script, dark mode through the role stylesheet; the meeting client (`/html5client`) takes the palette and the configured title through its own `customStyleUrl` and `clientTitle` settings
- 🧪 Workarounds for known Docker Compose issues

## Single Sign-On (SSO)

- Docs: [External Authentication](https://docs.bigbluebutton.org/greenlight/v3/external-authentication/)
- Supports:
  - ✅ OpenID Connect (OIDC)
  - 🧩 Custom OAuth2 flows via ENV vars

## Login methods

`services.bigbluebutton.login.method` declares `sso`, `native` and `registration`:

- `sso` renders the `OPENID_CONNECT_*` block of [templates/env.j2](./templates/env.j2). With it Greenlight v3 shows one Sign In button that posts to Keycloak and no Sign Up, and its API refuses every local sign-in except a SuperAdmin's and every local sign-up. Greenlight finds the account by `external_id`, the token's `sub` (`OPENID_CONNECT_UID_FIELD=sub`), and never by e-mail (`USE_EMAIL_AS_EXTERNAL_ID_FALLBACK=false`); [files/ruby/greenlight/ensure_admin.rb](./files/ruby/greenlight/ensure_admin.rb) gives the administrator the Keycloak id that [roles/web-app-keycloak/tasks/utils/directory_users.yml](../web-app-keycloak/tasks/utils/directory_users.yml) reads at deploy.
- `native` is the local email and password sign-in Greenlight offers whenever `OPENID_CONNECT_ISSUER` is unset. Greenlight has no switch of its own for it, so [tasks/04_login_methods.yml](./tasks/04_login_methods.yml) refuses an inventory that sets `native` equal to `sso`.
- `registration` sets the Greenlight site setting `RegistrationMethod` through [files/ruby/greenlight/registration_method.rb](./files/ruby/greenlight/registration_method.rb): `invite` while it is off, so the Sign Up entry disappears and only invited visitors register, and `open` while it or `sso` is on, because Greenlight also applies `RegistrationMethod` to the first OIDC sign-in and `invite` would refuse every new Keycloak account.
- Greenlight v3 has no own second factor and no LDAP sign-in.
- **Break-glass:** the role's administrator is a Greenlight `Administrator`, not a `SuperAdmin`, so with SSO on no form admits it. Reach the instance through the Rails runner of the `greenlight` container (`bundle exec rails runner`), the same channel [files/ruby/greenlight/ensure_admin.rb](./files/ruby/greenlight/ensure_admin.rb) uses.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `openid_connect` | `module` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

Greenlight ships its OpenID Connect strategy with the image and activates it from the `OPENID_CONNECT_*` block in [templates/env.j2](./templates/env.j2), so the addon's enablement derives directly from the `sso` service flag. Coupling is asserted by [files/playwright/addons/openid_connect.spec.js](./files/playwright/addons/openid_connect.spec.js).

## System Requirements

- Arch Linux with Docker, Compose, and NGINX roles pre-installed
- DNS and reverse proxy configuration using `sys-svc-proxy`
- Functional email system for Greenlight SMTP

## Further Resources

- [BigBlueButton Docker Docs](https://docs.bigbluebutton.org/greenlight/v3/install/)
- [Networking Fixes & Issues](https://stackoverflow.com/questions/53347951/web-app-network-not-found)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/Q7yW5QtrffnuDSQvmRZSXu)
