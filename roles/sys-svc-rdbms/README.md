# Central Database

## Description

This Ansible role provisions a centralized database system in your Docker Compose environment. It supports both MariaDB and PostgreSQL, providing a robust, scalable, and low-maintenance database solution. Whether you're consolidating your application's data or creating a dedicated central storage, this role simplifies setup and integration.

## Overview

Tailored for environments that require a central data repository, this role:

- Loads necessary database variables defined in vars/database.yml.
- Generates an environment file based on the chosen database engine.
- Integrates seamlessly with Docker Compose to deploy a centralized database container (if enabled).

## Cosmos

The diagram places Central Database in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-svc-rdbms 💻]
        svc_svc_rdbms["svc-rdbms"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The role's purpose is to automate the provisioning and configuration of a centralized database service. This not only reduces manual setup but also ensures consistent, reliable deployment across production and homelab environments.

## Features

- **Supports Multiple Engines:** Easily switch between MariaDB and PostgreSQL.
- **Centralized Data Management:** Improves data consistency and security.
- **Docker Compose Integration:** Automates container setup and configuration.
- **Simplified Variable Management:** Preconfigured templates minimize manual intervention.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
