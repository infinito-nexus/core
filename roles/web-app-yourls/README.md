# YOURLS

## Description

YOURLS (Your Own URL Shortener) is an open‑source URL shortening solution that enables you to create, track, and manage short links with ease. This deployment leverages Docker to provide a secure and easily scalable environment, ensuring that your YOURLS instance is configured for optimal performance and reliability.

## Overview

This containerized YOURLS solution is built on robust Docker Compose and Ansible automation. It simplifies the deployment process by integrating with centralized MariaDB management and providing pre‑configured health checks and environment settings. Whether you're looking to quickly generate memorable links or need detailed analytics, this deployment supports your digital strategy seamlessly.

## Features

- **Efficient URL Shortening:**  
  Quickly generate short, branded links that help streamline your online presence.

- **Built-in Analytics:**  
  Monitor link performance and track click data to gain valuable insights into user engagement.

- **Centralized Database Integration:**  
  Seamlessly connect to a MariaDB instance for consistent, reliable data storage and management.

- **Configurable Environment:**  
  Easily customize your YOURLS instance through environment variables: set your site URL, admin credentials, and more.

- **Secure and Scalable:**  
  Benefit from container isolation and reproducible deployments that ensure your service is both secure and scalable.

## Further Resources

- [YOURLS Official Website](https://yourls.org/)
- [YOURLS GitHub Repository](https://github.com/YOURLS/YOURLS)

## Persona contract opt-outs

YOURLS has no native SSO; the admin session is minted from the oauth2-proxy identity header by the `shunt_is_valid_user` drop-in in [`files/sso/infinito_sso.php`](./files/sso/infinito_sso.php), which honours the header only on the gated admin path and only for members of the YOURLS administrator group.
The gate itself admits only that same RBAC group ([`meta/services.yml`](./meta/services.yml)), so `biber` is rejected before YOURLS renders anything: [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true`, and the denial is asserted explicitly by `files/playwright/test-biber-denied.js`. The `administrator` persona stays live and exercises the bridge end to end.
