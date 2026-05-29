# web-app-pihole

Deploys [Pi-hole](https://pi-hole.net/) — a network-wide ad blocker — as a Docker-based service within the Infinito.Nexus platform.

## Features

- **OAuth2/SSO protection** via Keycloak and oauth2-proxy
- **RBAC** — only users in the `web-app-pihole-administrator` group can access the dashboard
- **OpenLDAP integration** for group synchronization
- **Logout button** injected into the Pi-hole admin navbar via JavaScript
- **Auto-redirect** from Pi-hole's root 403 page to `/admin/`
- **Redis** session storage for oauth2-proxy
- **Prometheus** metrics support

## Access

After deployment, Pi-hole is available at:
<https://pihole.<DOMAIN_PRIMARY>/admin/>

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
| 1 | Deploy without OAuth2 (standalone) |

## E2E Tests

Four Playwright scenarios are tested:

1. Pi-hole is protected — unauthenticated access redirects to Keycloak
2. Admin can log in via SSO and access the dashboard
3. Biber (non-admin) is denied access
4. Admin can log out via the logout button
