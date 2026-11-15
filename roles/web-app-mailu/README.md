# Mailu

> **End of life.** Infinito.Nexus neither maintains nor tests this role, and the
> default `INFINITO_LIFECYCLES` envelope keeps it out of every CI round. Deploy it
> at your own risk and take support from [upstream Mailu](https://mailu.io). Mailu is
> superseded by [`web-app-stalwart`](../web-app-stalwart/), the default email
> provider. New deployments MUST NOT adopt it and existing ones MUST migrate. Follow
> [Migration from Mailu](../web-app-stalwart/README.md#migration-from-mailu) to move
> the mailboxes over. Until then, set
> `applications.web-app-email.services.email.provider: web-app-mailu` to keep routing
> the mail abstraction ([web-app-email](../web-app-email/), `plugins/lookup/email.py`,
> `sys-svc-mail`) to Mailu.

## Description

Revolutionize your email communications with Mailu, a secure and flexible mail server solution that integrates comprehensive features like robust SMTP/IMAP support, advanced spam filtering, DKIM signing, and seamless webmail access. With its modern design and performance-oriented architecture, Mailu empowers you to manage digital correspondence with efficiency and reliability.

## Overview

Mailu is a complete mail server suite delivered as a Docker-based solution. It supports all essential email protocols, offers intuitive administration through a web interface, and integrates advanced security measures such as TLS encryption and virus scanning. Its modular architecture allows for scalable deployments and easy customization to suit diverse operational requirements.

More information about this role is available in these GitHub repositories:

- [Mailu](https://github.com/infinito-nexus/core/tree/main/roles/web-app-mailu)
- [Mailu-OIDC](https://github.com/heviat/Mailu-OIDC)

## Features

- **Comprehensive Email Protocols:** Supports SMTP, IMAP, and POP3 for reliable email delivery and retrieval.
- **Advanced Security:** Incorporates TLS encryption, DKIM, and SPF to secure your communications and prevent spoofing.
- **Integrated Spam Filtering and Antivirus:** Offers robust tools for spam detection and virus scanning, ensuring your inboxes remain clean and secure.
- **Customizable Webmail and Administration:** Provides a modern web interface for managing emails and administrative tasks with ease.
- **Flexible Deployment:** Easily scale and customize using Docker Compose, with configurable settings for networking, storage, and external services.
- **OIDC Support:** Optionally integrate with OpenID Connect for centralized authentication across your services.
- **Administrators and domain managers:** [files/python/rbac_sync.py](./files/python/rbac_sync.py) sets `global_admin` from the `web-app-mailu` `administrator` members and the managers of the mail domain from the `domain-manager` members through the Mailu REST API inside the admin container. Members are promoted, every other global administrator and domain manager is demoted. The platform administrator stays a global administrator. It runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer.
- **Login methods:** `services.mailu.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso` and `native`. `sso` switches the OIDC fork on (`OIDC_ENABLED` in [templates/env.j2](./templates/env.j2), driven by the `sso` service) and [templates/javascript.js.j2](./templates/javascript.js.j2) hides its `openid-connect/auth` link on `/sso/login` when the method is off. The fork has no setting that drops the local form, so with `native` off the same script hides the form of `/sso/login`, which serves the Webmail and the Admin sign-in alike. Self-registration stays off in every mode (no domain enables `signup_enabled`, `DOMAIN_REGISTRATION` is unset), and Mailu has no second factor of its own. Break-glass: `/sso/login?fallback=local` shows the form again for the platform administrator's mailbox, which keeps its password and the global administrator flag; the Mailu API (`API_TOKEN`) and `flask mailu` in the admin container remain as well.
- **DMARC Reports:** The published `_dmarc` record sends aggregate reports (`rua`) to `<username>@<mail domain>` of the user key in `services.mailu.dmarc.rua_user` (`platform_administrator` unless the inventory names another one). That user MUST carry a `mailbox` account or a `forward` to a user that carries one and whose `email` is that mailbox (`<username>@<mail domain>`), otherwise the deploy fails before any record is written.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Mailu Official Website](https://mailu.io/)
- [Mailu compose setup guide](https://mailu.io/2024.06/compose/setup.html)
- [SysPass issue #1299](https://github.com/nuxsmin/sysPass/issues/1299)
- [Mailu issue #1719](https://github.com/Mailu/Mailu/issues/1719)
- [Mailu issue #1171](https://github.com/Mailu/Mailu/issues/1171)
- [Mailu issue #2135](https://github.com/Mailu/Mailu/issues/2135)
- [Mailu issue #2827](https://github.com/Mailu/Mailu/issues/2827)
- [Mailu GitHub repository](https://github.com/Mailu/Mailu)
- [Gist by marienfressinaud](https://gist.github.com/marienfressinaud/f284a59b18aad395eb0de2d22836ae6b)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`. Mailu's OIDC fork interposes its own `/sso/login` page that carries a local login form next to an `openid-connect/auth` link, while the authenticated Roundcube surface carries an `openid-connect/logout` link; the shared helper matches login controls by accessible name and cannot tell the two apart, so it clicks logout. The administrator persona is blocked for a second, independent reason: Mailu's admin surface is a separate Flask app mounted at `WEB_ADMIN=/admin` (`templates/env.j2`), not the `/webmail/` surface the OIDC callback lands on.

Both journeys are covered bespoke in `files/playwright/playwright.spec.js`, which targets the `openid-connect/auth` href explicitly, opens `/admin`, and signs out at `/admin/ui/logout`; a second scenario drives the biber-to-administrator mail round-trip across two browser contexts. The path back to the generic personas is a distinguishable login control on Mailu's SSO page.
