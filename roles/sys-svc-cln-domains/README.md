# sys-svc-cln-domains

## Description

This Ansible role removes NGINX configuration files and revokes and deletes Certbot certificates for domains marked as deprecated.

## Overview

Optimized for idempotent cleanup operations, this role:

- Deletes NGINX server configuration files in `/etc/NGINX/conf.d/http/servers/` for each domain listed in `deprecated_domains`.
- Revokes and deletes corresponding Certbot certificates.
- Ensures cleanup tasks execute only once per playbook run.
- Notifies NGINX to restart after removing configurations.

## Purpose

Streamline the decommissioning of outdated or deprecated domains by automating the removal of NGINX server blocks and their SSL certificates.

## Features

- **NGINX Cleanup:** Safely removes server configuration files.
- **Certbot Integration:** Revokes and deletes certificates without manual intervention.
- **Idempotent Execution:** Utilizes a `run_once` flag to prevent repeated runs.
- **Service Notification:** Triggers an NGINX restart handler upon cleanup.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
