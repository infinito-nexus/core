# Mailu

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

## Further Resources

- [Mailu Official Website](https://mailu.io/)
- [Mailu compose setup guide](https://mailu.io/1.7/compose/setup.html)
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
