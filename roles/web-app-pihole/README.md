# web-app-pihole

Deploys [Pi-hole](https://pi-hole.net/) — a network-wide ad blocker — as a Docker-based service within the Infinito.Nexus platform.

## Description

Deploys [Pi-hole](https://pi-hole.net/) — a network-wide DNS sinkhole for ad and tracker blocking — with OAuth2/Keycloak SSO protection as part of the Infinito.Nexus stack.

## Overview

This role deploys Pi-hole as a containerized service within the Infinito.Nexus platform. Access is protected by OAuth2/Keycloak SSO, with RBAC enforced via OpenLDAP group membership.

## Features

- **OAuth2/SSO protection** via Keycloak and oauth2-proxy
- **RBAC** — only users in the `web-app-pihole-administrator` group can access the dashboard
- **OpenLDAP integration** for group synchronization
- **Logout button** injected into the Pi-hole admin navbar via JavaScript
- **Auto-redirect** from Pi-hole root 403 page to `/admin/`
- **Redis** session storage for oauth2-proxy
- **Prometheus** metrics support

## Access

After deployment, Pi-hole is available at:
`https://pihole.<DOMAIN_PRIMARY>/admin/`

Access is protected by SSO. Users must be members of the `web-app-pihole-administrator` group in Keycloak/LDAP.

## Dependencies

- `web-app-keycloak` — for SSO/OIDC authentication
- `svc-db-openldap` — for LDAP group synchronization

## Configuration

| Variable | Description | Default |
|---|---|---|
| `pihole.upstream_dns` | Upstream DNS servers | `{{ NETWORK_PUBLIC_DNS_RESOLVERS }}` |

## Variants

| Variant | Description |
|---|---|
| 0 | Default deploy with OAuth2/Keycloak protection |

## E2E Tests

Four Playwright scenarios are tested:

1. Pi-hole is protected — unauthenticated access redirects to Keycloak
2. Admin can log in via SSO and access the dashboard
3. Biber (non-admin) is denied access
4. Admin can log out via the logout button

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
