# Stalwart Mail Server

## Description

Runs [Stalwart](https://stalw.art/) — a secure, all-in-one mail and
collaboration server — as the platform's email provider. A single hardened
service speaks **SMTP, Submission, IMAP, POP3, JMAP, ManageSieve, CalDAV,
CardDAV and WebDAV**, with a **built-in spam filter**, **DKIM/DMARC** signing
and a **WebAdmin + REST management API**.

This role replaces the deprecated [`web-app-mailu`](../web-app-mailu/) role.
Applications send mail through the same provider-agnostic abstraction
(`lookup('email')` / [`sys-svc-mail`](../sys-svc-mail/)) — no consumer changes
are needed beyond the provider repoint.

## Overview

Compared with Mailu's multi-container stack, Stalwart collapses the mail server
into one binary. This role runs:

| Container | Purpose |
|-----------|---------|
| `stalwart` | SMTP/IMAP/JMAP/POP3/Sieve/DAV + built-in spam filter + WebAdmin/REST API |
| `webmail` (Roundcube) | Browser webmail (parity with Mailu) |
| `postgres` *(shared)* | Account / mail / metadata store |
| `redis` *(shared)* | In-memory / rate-limit store |

Dynamic state (domains, accounts, passwords, DKIM, certificates) is administered
at runtime via the JMAP management API; `config.json` only bootstraps the data
store. (Stalwart's spam filter is built in, so no separate ClamAV container is
needed.)

## SSO (Keycloak / OpenID Connect)

When `web-app-keycloak` is present the role joins the shared Keycloak client and
delegates **interactive** authentication to Keycloak:

- **WebAdmin + IMAP/SMTP/JMAP** authenticate against an **OIDC directory**
  (`tasks/08_oidc.yml`): Stalwart validates Keycloak-issued tokens, matching the
  `preferred_username` claim to the provisioned account.
- **Roundcube** logs users in over OAuth2 and talks to Stalwart with **XOAUTH2**
  (`templates/roundcube-oauth.inc.php.j2`).

**Design constraint (validated against the live JMAP schema):** Stalwart's
authentication directory is *Internal XOR one external directory* — there is no
chaining or fallback. Enabling SSO therefore **disables password submission**
for every account, including the machine `no-reply` account. To keep outbound
notifications working, the role:

1. Widens `x:MtaStageRcpt.allowRelaying` to trust the internal Docker networks
   (`STALWART_TRUSTED_NETWORKS`), so the bot relays without SMTP AUTH; and
2. Self-declares `services.sso.oidc.submission_via_relay: true`, which makes
   [`plugins/lookup/email.py`](../../plugins/lookup/email.py) switch the
   `no-reply` client to unauthenticated STARTTLS relay on port 25.

With SSO disabled the role uses the Internal directory and password submission,
exactly as before. Mailu keeps password submission in both modes and does not
set `submission_via_relay`.

## Features

- All-in-one mail server (SMTP/IMAP/JMAP/POP3/ManageSieve)
- CalDAV / CardDAV / WebDAV collaboration
- Built-in spam filtering
- DKIM signing with automatic key management; SPF / DMARC published in DNS
- OpenID Connect SSO via Keycloak
- Roundcube webmail
- PostgreSQL + Redis backing stores

## Further Reading

- [Stalwart documentation](https://stalw.art/docs)
- [`sys-svc-mail`](../sys-svc-mail/) — how applications send mail
- [`plugins/lookup/email.py`](../../plugins/lookup/email.py) — the email abstraction

> **Note:** Stalwart's `config.toml` schema and management API endpoints are
> version-sensitive. Pin `services.stalwart.version` and validate the bootstrap
> config and provisioning tasks against that release on first deployment
> (`# @todo` markers flag the spots to confirm).

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
