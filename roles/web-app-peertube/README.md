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
  The work splits by channel, because in swarm PeerTube and its database can run on different nodes and PeerTube publishes no host port there. At deploy time, once on the stack host, [tasks/rbac/provision.yml](./tasks/rbac/provision.yml) runs [files/python/rbac/provision.py](./files/python/rbac/provision.py) inside PeerTube's network namespace on its node: as root it creates the accounts of the `administrator` and `moderator` role group members that have an e-mail and no account yet. A member whose username or e-mail a local account of somebody else holds is not created but named as a warning, because that account could be a self-registration waiting for the member's role; the warning does not fail the deploy, so a stranger's signup cannot block it. A member whose username or e-mail an OpenID Connect account already holds is skipped, since PeerTube keeps the e-mail it first saw and the directory may have changed it since. It retries the whole run three times, 10 seconds apart; a 409 counts only when an account with the member's username and e-mail exists afterwards. A creation error that outlasts the retries fails the deploy after the hook below has run, so one bad member blocks neither the linking nor a demotion. The deploy also fails when the stack host is not among the play's hosts, instead of skipping the creation. Unlike the former hook, the timer does not retry a creation, so such a failure waits for the next deploy. [files/python/rbac/sync.py](./files/python/rbac/sync.py) then runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) on the node of the database container, at every deploy and on its timer, and only talks SQL: [files/sql/rbac/link-preprovisioned-accounts.sql](./files/sql/rbac/link-preprovisioned-accounts.sql) hands a local account to the OIDC plugin only when one role group member carries both its username and its e-mail and nobody has used it yet (no `lastLoginDate`, no OAuth token), so an account a failed deploy created but never linked is linked on the next run while an account someone registered and logged into is never taken over, and [files/sql/rbac/reconcile-roles.sql](./files/sql/rbac/reconcile-roles.sql) converges the PeerTube role of every OpenID Connect account to Administrator, Moderator or User from its groups. The same statement deletes every password-grant token of an OpenID Connect account: PeerTube refuses password logins to those, so such a token only stems from a login that read the account just before the link committed. A member added between deploys therefore has its role within one timer interval once the account exists, and gets a pre-provisioned account at the next deploy or its own at the first OIDC login. The local `root` account keeps its role, and its password never reaches the hook.

- **Login methods:**
  `services.peertube.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `native`, `2fa` and `registration`. `registration` sets `PEERTUBE_SIGNUP_ENABLED` and `sso` together with `native` sets `PEERTUBE_CLIENT_MENU_LOGIN_REDIRECT_ON_SINGLE_EXTERNAL_AUTH`, so the header login link goes straight to Keycloak while the OIDC entry is the only one ([templates/env.j2](./templates/env.j2)). PeerTube has no setting that drops the local form, the OIDC entry or the TOTP second factor, so [templates/javascript.js.j2](./templates/javascript.js.j2) hides the `/login` form while `native` is off, the "Sign in with" block while `sso` is off and the two-factor section of the account settings while `2fa` is off; PeerTube has no setting that requires its TOTP second factor, so `login.method.2fa.enforced` only offers it for enrollment here. Break-glass: `/login?fallback=local` shows the form again for the local `root` account; the OAuth password grant of `/api/v1/users/token` that [tasks/03_admin.yml](./tasks/03_admin.yml) uses stays open as well.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `peertube-plugin-auth-openid-connect` | `plugin` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

The plugin is installed through PeerTube's own `plugin:install` and its settings row is upserted by [tasks/oidc/enable.yml](./tasks/oidc/enable.yml), so its enablement derives directly from the `sso` service flag. Coupling is asserted by [files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js](./files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js).

## Developer Notes

The native `root` account signs in with the **first 50 characters** of the platform administrator's password, not the whole secret. PeerTube caps a user password at 50 characters and 72 bytes (`CONSTRAINTS_FIELDS.USERS.PASSWORD`, "Limited by bcrypt algorithm"), and a declared user's password is 64 characters: handed over in full, `/api/v1/users/token` answers `too_long_password` and `npm run reset-password` refuses it with "New password is invalid.". `PEERTUBE_ROOT_PASSWORD` in [vars/main.yml](./vars/main.yml) is the single place that bounds it; the deploy, the design token and `templates/playwright.env.j2` all read it from there. Signing in through Keycloak uses the full password.

See [Upgrade.md](./Upgrade.md) for guidance on upgrading your PeerTube deployment.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [PeerTube Official Documentation](https://docs.joinpeertube.org/install-docker)
- [PeerTube GitHub Issues](https://github.com/Chocobozzz/PeerTube/issues/3091)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/VN7YZTQM34SyQJDeXU5Q2B)
