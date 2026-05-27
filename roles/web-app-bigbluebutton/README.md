# BigBlueButton

## Description

This Ansible role deploys [BigBlueButton](https://bigbluebutton.org/) using Docker Compose. It includes support for Greenlight, OIDC, LDAP, TURN/STUN, health checks, and a modular `.env` setup. This role is ideal for educational institutions and teams requiring a self-hosted video conferencing solution.
> 🔧 **Note**: The database layer should be decoupled in a future release to improve modularity and integration.
>
## Overview

This role provides a fully automated deployment of [BigBlueButton](https://bigbluebutton.org/) using Docker Compose on Arch Linux. It manages the entire lifecycle of the deployment, from cloning the upstream Docker repository and generating the `.env` configuration to customizing `compose.yml` for volume usage, WebSocket proxying, and optional LDAP/OIDC integration.
The setup includes conditional Greenlight activation, WebRTC support via TURN/STUN, and various fixes for known container orchestration issues. The role is modular and integrates seamlessly with the Infinito.Nexus infrastructure, including reverse proxy configuration, domain management, and secrets templating.
By default, BigBlueButton is deployed with best-practice hardening, modular secrets, and support for multiple authentication methods and scalable storage backends.

## Features

- 🐳 **Docker-based** deployment via official [bigbluebutton/docker](https://github.com/bigbluebutton/docker)
- ✅ **Greenlight** (v3) frontend support
- 🔐 **SSO with OIDC & LDAP** (optional)
- 🧱 Automatic `.env` templating and domain/NGINX integration
- 🛠 Volume patching and Docker Compose customization
- 📬 SMTP integration and Greenlight admin creation
- 🧪 Workarounds for known Docker Compose or Etherpad issues

## Single Sign-On (SSO)

- Docs: [External Authentication](https://docs.bigbluebutton.org/greenlight/v3/external-authentication/)
- Supports:
  - ✅ OpenID Connect (OIDC)
  - ✅ LDAP (with custom DN and filters)
  - 🧩 Custom OAuth2 flows via ENV vars

## System Requirements

- Arch Linux with Docker, Compose, and NGINX roles pre-installed
- DNS and reverse proxy configuration using `sys-svc-proxy`
- Functional email system for Greenlight SMTP

## Further Resources

- [BigBlueButton Docker Docs](https://docs.bigbluebutton.org/greenlight/v3/install/)
- [Networking Fixes & Issues](https://stackoverflow.com/questions/53347951/web-app-network-not-found)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
