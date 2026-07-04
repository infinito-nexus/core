# Checkmk

## Description

[Checkmk](https://checkmk.com/) (Raw / Community edition, 100% open source) is an IT and application monitoring system. This role deploys the official all-in-one `checkmk/check-mk-raw` container behind the Infinito.Nexus reverse proxy, with Keycloak SSO via the oauth2-proxy gate and native LDAP user management.

## Overview

Checkmk Raw bundles its own monitoring core (Nagios), RRD storage, and an Apache-served web GUI, so it needs no external database. All state lives on one persistent volume mounted at `/omd/sites`, and the GUI is served under the OMD site path (`/cmk/check_mk/`). The image is pinned to `checkmk/check-mk-raw:2.4.0p32` in `meta/services.yml`; Checkmk renamed the Raw image to `check-mk-community` from 2.5, so bump the tag only after reviewing the upstream [version notes](https://docs.checkmk.com/latest/en/cmk_versions.html).

## Features

- **Open-source monitoring:**
  Hosts, services, metrics, and alerting from the Checkmk Raw all-in-one container.

- **Keycloak SSO:**
  Fronted by the platform oauth2-proxy gate; the authenticated user is passed to Checkmk via the trusted `X-Remote-User` header (`auth_by_http_header`), so no second login prompt appears.

- **Native LDAP:**
  A central-OpenLDAP connection supplies user records, roles, and contact groups; the header user (Keycloak `preferred_username`) resolves to a real Checkmk user.

- **No external database:**
  Self-contained on a single persistent volume.

- **Agent receiver:**
  Container port 8000 is mapped to a host port (`local.agent`); external proxying for remote-host TLS agent registration is a follow-up.

- **Break-glass `cmkadmin`:**
  Seeded on first run via `CMK_PASSWORD`; reachable via the local login form only when the SSO gate is absent.

## Further Resources

- [Checkmk Docker docs](https://docs.checkmk.com/latest/en/introduction_docker.html)
- [LDAP user management](https://docs.checkmk.com/latest/en/ldap.html)
- [HTTP header authentication (Werk #7819)](https://checkmk.com/werk/7819)
- [Checkmk GitHub Repository](https://github.com/Checkmk/checkmk)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
