# Mastodon

## Description

Dive into a decentralized social experience with Mastodon, a vibrant platform that redefines online communication with its federated, community-driven approach. With a rich set of features focused on privacy, scalability, and customization, Mastodon empowers users to create, share, and interact in an open social network.

## Overview

This role deploys Mastodon using Docker, streamlining the installation and configuration of a full-featured social networking platform. Mastodon is built to support federation across multiple instances, offering robust content moderation, real-time updates, and flexible API integrations. Its advanced architecture includes separate services for the web frontend, streaming API, and background job processing, ensuring high performance and scalability for large communities.

## Features

- **Decentralized Network:** Connect with users across multiple instances in a federated social media ecosystem.
- **Real-Time Streaming:** Enjoy dynamic updates and real-time content delivery through dedicated streaming services.
- **Robust Content Moderation:** Utilize powerful moderation tools to manage community interactions and maintain safe spaces.
- **Scalable Architecture:** Benefit from a multi-service, Docker-based setup that supports high user loads and seamless background processing.
- **Flexible Authentication:** Integrated support for OpenID Connect (OIDC) simplifies user login and enhances security.
- **Roles From Keycloak Groups:** Every OIDC login sets the Mastodon role from the `groups` claim. The `administrator` role group grants `Admin`, the `moderator` role group grants `Moderator`, and an account outside both loses either role. Accounts that hold `Owner` or a role created in Mastodon stay untouched, so the platform administrator keeps `Owner`.
- **Login methods:** `services.mastodon.login.method` declares `sso`, `native`, `2fa` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). `sso` renders the `OIDC_*` block of [`templates/env.j2`](./templates/env.j2). With `sso` on, `native` drives `OMNIAUTH_ONLY` (`true` while `native` is off, so the e-mail and password form and the sign-up link disappear); without `sso` the form is the only sign-in. `registration` sets the `registrations_mode` setting (`open` or `none`) through [`files/ruby/ensure/registrations_mode.rb`](./files/ruby/ensure/registrations_mode.rb) on every deploy ([`tasks/07_login_methods.yml`](./tasks/07_login_methods.yml)); a Keycloak sign-in creates its account in either mode. `2fa` covers Mastodon's own second factor (TOTP, security keys), which has no setting to switch it off: while `2fa` is off, the `javascript` service of [`meta/services.yml`](./meta/services.yml) is on and injects [`templates/javascript.js.j2`](./templates/javascript.js.j2), which hides the two-factor and security-key entries of the settings. Accounts that already enrolled keep their second factor at sign-in. Mastodon has no setting that requires a second factor, so `login.method.2fa.enforced` only offers it here.
- **Break-glass access:** with SSO on and `native` off, the local administrator of [`tasks/05_administrator.yml`](./tasks/05_administrator.yml) has no form. Recovery runs through the CLI in the Mastodon container (`bin/tootctl accounts modify <user> --reset-password`, `bin/tootctl settings`), and overriding `services.mastodon.login.method.native.enabled: true` in the inventory sets `OMNIAUTH_ONLY=false`, after which the administrator signs in at `/auth/sign_in` with its e-mail and password.
- **Customizable User Experience:** Configure themes, timeline settings, and notification options to tailor the social experience to your community.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Mastodon Official Website](https://joinmastodon.org/)
- [Mastodon Documentation](https://docs.joinmastodon.org/)
- [Mastodon Configuration Guide](https://gist.github.com/TrillCyborg/84939cd4013ace9960031b803a0590c4)
- [Scaling a Mastodon Server](https://www.digitalocean.com/community/tutorials/how-to-scale-your-mastodon-server)
- [Mastodon GitHub Issues](https://github.com/mastodon/mastodon/issues/7958)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/3ciPoGk91eAPuPBom7a6kw)

## Persona contract opt-outs

[`tasks/05_administrator.yml`](./tasks/05_administrator.yml) creates the account and converges its password to `ADMIN_PASSWORD`, but the shared persona flow fills `ADMIN_USERNAME` into the native form while Mastodon's `/auth/sign_in` only accepts the e-mail in `user[email]`, so the journey cannot sign in natively; `biber` has no Mastodon account at all, since the OIDC sign-in ([`templates/env.j2`](./templates/env.j2)) is the only path that would create one. In the `services.sso.enabled: false` matrix variants that path is removed, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The SeaweedFS companion scenario ([`files/playwright/test-seaweedfs.js`](./files/playwright/test-seaweedfs.js)) drives the same admin journey and skips on the same flag.
