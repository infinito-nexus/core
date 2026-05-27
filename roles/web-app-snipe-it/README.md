# Snipe‑IT

## Description

Snipe‑IT is an open‑source asset management system designed to streamline hardware and software inventory tracking. This deployment provides an automated, containerized solution using Docker Compose, centralized MariaDB database integration, and secure, configurable environment settings, including robust SMTP email support and pending SAML authentication enhancements.

## Overview

This Docker deployment uses Ansible automation to set up Snipe‑IT along with necessary services such as a MariaDB database, an optional OAuth2 proxy for additional security, and a reverse proxy configuration. The system is built for reliable asset management in various environments.

## Features

- **Automated Deployment:**  
  Launch Snipe‑IT quickly with Docker Compose and Ansible automation for a production‑ready platform.

- **Centralized Database Support:**  
  Leverage MariaDB for secure and reliable data storage.

- **Configurable SMTP Settings:**  
  Manage email notifications and alerts with customizable SMTP configurations.

- **Optional SAML Authentication:**  
  Prepare for enhanced, standards‑based authentication (integration pending).

- **Redis Caching:**  
  Improve application performance with built‑in Redis caching support.

## Other Resources

- [Snipe‑IT Official Documentation](https://snipe-it.readme.io/)
- [Mattermost SSO Integration Guide](https://docs.mattermost.com/onboard/sso-saml-keycloak.html)
- [Additional GitHub Issues and Discussions](https://github.com/snipe/snipe-it/issues)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
