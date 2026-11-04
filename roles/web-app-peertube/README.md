# PeerTube

## Description

PeerTube is a decentralized, open-source video hosting platform that empowers creators to share videos without relying on centralized services. It leverages federated architecture and peer-to-peer technologies to provide scalable, secure, and community-driven video streaming.

## Overview

This Docker Compose deployment sets up PeerTube with integrated support for essential services such as a PostgreSQL database, Redis cache, and an NGINX reverse proxy for secure HTTPS termination and domain routing. The configuration supports advanced security settings, modular service scaling, and automated environment injection.

## Features

- **Decentralized Video Hosting:**
  Distribute video hosting across multiple instances to enhance resilience and avoid single-point control.

- **Scalability and Performance:**
  Efficiently manage video transcoding, live streaming, and storage through containerized microservices.

- **Customizable Configuration:**
  Tailor settings such as storage, email delivery, and administrative parameters using environment variables and configuration files.

- **Secure and Private:**
  Built-in support for TLS, secure SMTP integration, and strict administrative controls to ensure data protection.

- **Federated Communication:**
  Designed to operate within a federated network, enabling seamless sharing and interconnection with other PeerTube instances.

- **Automatic Upgrades:**
  Detects the release the existing data was written by, runs the upstream migration scripts up to the pinned release and reseeds the client assets, see [Upgrade.md](./Upgrade.md).

- **Profile from the identity provider:**
  An account created through the OpenID Connect plugin takes its display name, email and interface language from the `name`, `email` and `locale` claims.

- **Role groups:**
  [files/python/rbac_sync.py](./files/python/rbac_sync.py) runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. It creates the OpenID Connect accounts of the `administrator` and `moderator` role group members that have an e-mail and no account yet through the PeerTube API as root, hands them to the OIDC plugin, and then runs [files/sql/rbac/reconcile-roles.sql](./files/sql/rbac/reconcile-roles.sql) through `psql` in the database container, which converges the PeerTube role of every OpenID Connect account to Administrator, Moderator or User from its groups. A member added between deploys therefore has its account and role within one timer interval. The local `root` account keeps its role.

- **Login methods:**
  `services.peertube.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `native`, `2fa` and `registration`. `registration` sets `PEERTUBE_SIGNUP_ENABLED` and `sso` together with `native` sets `PEERTUBE_CLIENT_MENU_LOGIN_REDIRECT_ON_SINGLE_EXTERNAL_AUTH`, so the header login link goes straight to Keycloak while the OIDC entry is the only one ([templates/env.j2](./templates/env.j2)). PeerTube has no setting that drops the local form, the OIDC entry or the TOTP second factor, so [templates/javascript.js.j2](./templates/javascript.js.j2) hides the `/login` form while `native` is off, the "Sign in with" block while `sso` is off and the two-factor section of the account settings while `2fa` is off; PeerTube offers its TOTP second factor for enrollment and never enforces it. Break-glass: `/login?fallback=local` shows the form again for the local `root` account; the OAuth password grant of `/api/v1/users/token` that [tasks/03_admin.yml](./tasks/03_admin.yml) uses stays open as well.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `peertube-plugin-auth-openid-connect` | `plugin` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

The plugin is installed through PeerTube's own `plugin:install` and its settings row is upserted by [tasks/oidc/enable.yml](./tasks/oidc/enable.yml), so its enablement derives directly from the `sso` service flag. Coupling is asserted by [files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js](./files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js).

## Developer Notes

The native `root` account signs in with the **first 50 characters** of the platform administrator's password, not the whole secret. PeerTube caps a user password at 50 characters and 72 bytes (`CONSTRAINTS_FIELDS.USERS.PASSWORD`, "Limited by bcrypt algorithm"), and a declared user's password is 64 characters: handed over in full, `/api/v1/users/token` answers `too_long_password` and `npm run reset-password` refuses it with "New password is invalid.". `PEERTUBE_ROOT_PASSWORD` in [vars/main.yml](./vars/main.yml) is the single place that bounds it; the deploy, the design token and `templates/playwright.env.j2` all read it from there. Signing in through Keycloak uses the full password.

See [Upgrade.md](./Upgrade.md) for guidance on upgrading your PeerTube deployment.

## Further Resources

- [PeerTube Official Documentation](https://docs.joinpeertube.org/install-docker)
- [PeerTube GitHub Issues](https://github.com/Chocobozzz/PeerTube/issues/3091)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/VN7YZTQM34SyQJDeXU5Q2B)
