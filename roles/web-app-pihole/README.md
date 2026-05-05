# Pi-hole

Deploys [Pi-hole](https://pi-hole.net/) — a network-wide DNS sinkhole for ad and tracker blocking — as part of the Infinito.Nexus stack.

## Features

- Single-container deployment via Docker Compose
- Network-wide DNS-level ad and tracker blocking
- OAuth2 proxy via Keycloak for access control (RBAC)
- Redis session store for OAuth2 proxy
- Web dashboard accessible at `https://pihole.<your-domain>`
- DNS service exposed on port 53 (TCP/UDP)
- Upstream DNS configurable per inventory (default: Cloudflare `1.1.1.1`)

## Authentication

Pi-hole's native web interface is protected by **OAuth2 proxy** backed by Keycloak. Only users in the `web-app-pihole-administrator` LDAP group have access to the dashboard.

Pi-hole's own password authentication is automatically disabled when OAuth2 is active.

## Configuration

Key settings in `meta/services.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `oauth2.enabled` | `true` | Enable Keycloak OAuth2 proxy protection |
| `oauth2.origin.host` | `pihole` | Backend container name |
| `oauth2.origin.port` | `80` | Backend container port |
| `pihole.image` | `pihole/pihole` | Docker image |
| `pihole.version` | `latest` | Docker image tag |
| `pihole.ports.local.http` | `8041` | Host-bound HTTP port |
| `pihole.ports.local.oauth2` | `16493` | Host-bound OAuth2 proxy port |

Upstream DNS can be overridden in your inventory:

```yaml
applications:
  web-app-pihole:
    pihole:
      upstream_dns: "9.9.9.9;149.112.112.112"
```

## Upstream DNS Options

| Provider | Value |
|----------|-------|
| Cloudflare | `1.1.1.1;1.0.0.1` |
| Google | `8.8.8.8;8.8.4.4` |
| Quad9 (filtered) | `9.9.9.9;149.112.112.112` |
| Quad9 (unfiltered) | `9.9.9.10;149.112.112.10` |
| OpenDNS | `208.67.222.222;208.67.220.220` |

## DNS Configuration

Point your router's DHCP DNS setting to the host running Pi-hole so all network devices use it automatically. Pi-hole listens on port 53 (TCP/UDP) on `{{ DOCKER_BIND_HOST }}`.

## Known Limitations

- Pi-hole v6 gravity blocklist downloads via FTL — if the default blocklist fails to download, add it manually via the Pi-hole admin UI under **Lists**.
- Internal `*.infinito.example` domains are not resolved by Pi-hole by default. A conditional forwarder to CoreDNS is planned as a follow-up.

## References

- [Pi-hole documentation](https://docs.pi-hole.net/)
- [Pi-hole Docker image](https://github.com/pi-hole/docker-pi-hole)
- [Blocklist collection](https://firebog.net/)
