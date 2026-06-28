# Checkmk

## Description

[Checkmk](https://checkmk.com/) (Raw / Community edition — 100% open source) is an IT and application monitoring system. This role deploys the official all-in-one `checkmk/check-mk-raw` container behind the Infinito.Nexus reverse proxy, with Keycloak SSO via the oauth2-proxy gate and native LDAP user management.

## Overview

Checkmk Raw bundles its own monitoring core (Nagios), RRD storage, and an Apache-served web GUI — it needs **no external database**. All state lives on one persistent volume mounted at `/omd/sites`. The GUI is served under the OMD site path (`/cmk/check_mk/`).

## Features

- **Open-source monitoring** — hosts, services, metrics, and alerting from the Checkmk Raw all-in-one container.
- **Keycloak SSO** — fronted by the platform oauth2-proxy gate; the authenticated user is passed to Checkmk via the trusted `X-Remote-User` header (`auth_by_http_header`).
- **Native LDAP** — a central-OpenLDAP connection supplies user records, roles, and contact groups.
- **No external database** — self-contained on a single persistent volume.
- **Agent receiver** — container port 8000 mapped to a host port (`local.agent`); external proxying for remote-host TLS agent registration is a follow-up.

## Authentication & admin model

Checkmk Raw has **no native OIDC** (SAML is commercial-only; OIDC only via manual Apache modules), but **LDAP is native in every edition**. The role therefore combines:

- **oauth2-proxy gate** (`services.sso.flavor: oauth2`) — the platform sidecar authenticates against Keycloak; the role's `templates/proxy.conf.j2` injects the authenticated user as `X-Remote-User`.
- **Checkmk header-auth** — `auth_by_http_header = "X-Remote-User"` is written into the site so the proxy-supplied user is logged in without a second prompt.
- **Native LDAP connection** — provisioned into the site so the header user (Keycloak `preferred_username`) resolves to a real Checkmk user with roles/contact groups.
- **Break-glass `cmkadmin`** — seeded on first run via `CMK_PASSWORD`; reachable via the local login form only when the SSO gate is absent (V2).

> The in-site configuration (`files/configure-sso.sh`) writes `auth_by_http_header` and the LDAP `user_connections` structure. The LDAP structure is version-sensitive (written for the pinned 2.4 line) and **must be confirmed on the first live deploy**; each generated `.mk` is Python-syntax-checked before the Apache reload so a typo cannot 500 the GUI.

## Variant matrix

| Variant | `sso` | `ldap` | Login |
| --- | --- | --- | --- |
| V1 | on | on | Keycloak via oauth2 gate → header-auth; LDAP supplies the user record. |
| V2 | off | off | `cmkadmin` local form only. |
| V3 | off | on | local form + LDAP-form users (no Keycloak gate). |

## Ports

- `5000` (GUI) → proxied under the canonical domain.
- `8000` (agent receiver) → mapped to a host port (`local.agent`) per Decision #4; external proxying for remote agents is a follow-up.

## Image & bump policy

Pinned to `checkmk/check-mk-raw:2.4.0p32` in [`meta/services.yml`](./meta/services.yml) (never `:latest`). Note Checkmk renamed the Raw image to `check-mk-community` from 2.5; bump by editing the tag after reviewing the upstream [version notes](https://docs.checkmk.com/latest/en/cmk_versions.html).

## Further Resources

- [Checkmk Docker docs](https://docs.checkmk.com/latest/en/introduction_docker.html)
- [LDAP user management](https://docs.checkmk.com/latest/en/ldap.html)
- [HTTP header authentication (Werk #7819)](https://checkmk.com/werk/7819)
- [Checkmk GitHub Repository](https://github.com/Checkmk/checkmk)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
