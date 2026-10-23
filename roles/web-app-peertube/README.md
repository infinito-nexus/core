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

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `peertube-plugin-auth-openid-connect` | `plugin` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

The plugin is installed through PeerTube's own `plugin:install` and its settings row is upserted by [tasks/oidc/enable.yml](./tasks/oidc/enable.yml), so its enablement derives directly from the `sso` service flag. Coupling is asserted by [files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js](./files/playwright/addons/peertube-plugin-auth-openid-connect.spec.js).

## Developer Notes

The native `root` account signs in with the **first 50 characters** of the platform administrator's password, not the whole secret. PeerTube caps a user password at 50 characters and 72 bytes (`CONSTRAINTS_FIELDS.USERS.PASSWORD`, "Limited by bcrypt algorithm"), and a declared user's password is 64 characters: handed over in full, `/api/v1/users/token` answers `too_long_password` and `npm run reset-password` refuses it with "New password is invalid.". `PEERTUBE_ROOT_PASSWORD` in [vars/main.yml](./vars/main.yml) is the single place that bounds it; the deploy, the design token and `templates/playwright.env.j2` all read it from there. Signing in through Keycloak uses the full password.

See [Upgrade.md](./Upgrade.md) for guidance on upgrading your PeerTube deployment.

## Further Resources

- [PeerTube Official Documentation](https://docs.joinpeertube.org/install-docker)
- [PeerTube GitHub Issues](https://github.com/Chocobozzz/PeerTube/issues/3091)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/VN7YZTQM34SyQJDeXU5Q2B)
