# Nextcloud

## Description

Elevate your collaboration with Nextcloud, a vibrant self-hosted cloud solution designed for dynamic file sharing, seamless communication, and effortless teamwork. Nextcloud offers a full suite of integrated tools (including LDAP and OIDC authentication, Redis caching, and automated plugin management via OCC) to empower a secure, extensible, and production-ready cloud environment.

## Overview

This role provisions a complete Nextcloud deployment using Docker Compose. It automates the setup of the Nextcloud application along with its underlying MariaDB database and configures the system for secure public access via an NGINX reverse proxy. The deployment includes automated configuration merging into `config.php`, health check routines, and integrated support for backup and recovery operations.

## Features

- **Fully Dockerized Deployment:** Simplifies installation using Docker Compose for the Nextcloud application and its MariaDB backend.
- **Secure Access:** Integrates with an NGINX reverse proxy for encrypted, high-performance access.
- **Robust Authentication:** Supports LDAP and OIDC for secure identity and access management.
- **Automated Configuration Management:** Uses additive configuration files to dynamically merge system settings into `config.php`.
- **Integrated Backup & Recovery:** Provides built-in support for backup and restoration operations to safeguard your data.
- **Extensible Plugin Framework:** Easily manage and configure hundreds of Nextcloud plugins using the OCC command line tool.

## Documentation

A detailled documentation for the use and administration of Nextcloud on Infinito.Nexus you will find [here](docs/README.md)

## Further Resources

- [Nextcloud Official Website](https://nextcloud.com/)
- [Nextcloud Docker Documentation](https://github.com/nextcloud/docker)
- [Nextcloud Admin Manual](https://docs.nextcloud.com/server/latest/admin_manual/)
- [LDAP Integration Guide](https://docs.nextcloud.com/server/latest/admin_manual/configuration_user/user_auth_ldap.html)
- [OIDC Login Plugin (pulsejet)](https://github.com/pulsejet/nextcloud-oidc-login)
- [Sociallogin Plugin (Official)](https://apps.nextcloud.com/apps/sociallogin)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
