# sys-svc-cln-domains

## Description

This Ansible role removes NGINX configuration files and revokes and deletes Certbot certificates for domains marked as deprecated.

## Overview

Optimized for idempotent cleanup operations, this role:

- Deletes NGINX server configuration files in `/etc/NGINX/conf.d/http/servers/` for each domain listed in `deprecated_domains`.
- Deletes every `<domain>.conf` below the servers directory whose domain is not in `CURRENT_PLAY_DOMAINS_ALL`, the domains of every application in the host's `group_names` and their dependencies, including redirect sources; files not named after a domain and `.onion` services stay. Both cleanups run only with `MODE_CLEANUP`.
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
