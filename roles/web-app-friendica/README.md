# Friendica

## Description

Empower your decentralized social networking with Friendica, a platform designed to foster communication and community building with ease. Experience a robust, containerized deployment that streamlines installation, configuration, and maintenance for your Friendica instance.

## Overview

This role deploys Friendica using Docker, managing the Friendica application container alongside a central MariaDB instance. It provides tools for full resets, manual and automatic database reinitialization, email and general configuration debugging, and autoinstall processes, all to ensure your Friendica installation remains reliable and easy to maintain.

## Features

- **Decentralized Social Networking:** Facilitate a distributed network for seamless peer-to-peer communication.
- **Containerized Deployment:** Leverage Docker for streamlined setup, management, and scalability.
- **Robust Reset and Recovery Tools:** Easily reset and reinitialize both the application and its underlying database.
- **Configuration Debugging:** Quickly inspect environment variables, volume data, and configuration files to troubleshoot issues.
- **Autoinstall Capability:** Automate initial installation steps to rapidly deploy a working Friendica instance.

## Addons

Role-level extensions are declared in `meta/addons/`
(unified addon contract, requirement 026):

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `ldapauth` | `addon` | enabled whenever the `ldap` service is present (`svc-db-openldap` co-deployed) | `ldap` → `svc-db-openldap` |

`ldapauth` is the only path that materialises a `friendica.user` row, so its enablement derives directly from the `ldap` service flag.
The oauth2-proxy `sso` gate in front of the vhost is a front-door auth gate, not an addon bridge, and stays in [`meta/services.yml`](./meta/services.yml).
The LDAP login path is covered by the existing LDAP Playwright spec (requirement 018), so no addon-specific spec is added.

## Further Resources

- [Friendica Docker Hub](https://hub.docker.com/_/friendica)
- [Friendica Installation Documentation](https://wiki.friendi.ca/docs/install)
- [Friendica GitHub Repository](https://github.com/friendica/docker)
- [Relevant Issue Tracker](https://github.com/friendica/friendica/issues)
