# Administrator User

## Description

This role creates a dedicated administrator user for local administrative tasks. The administrator account is configured to require a password when executing [sudo](https://en.wikipedia.org/wiki/Sudo), ensuring secure privilege escalation. For security reasons, it is recommended to use this dedicated administrator user instead of the default root account.

SSH key management follows a **single point of truth**: keys must be provided via `lookup('users', 'administrator').authorized_keys` (**must contain at least one SSH public key**), and are deployed to the administrator’s `authorized_keys` file.

## Overview

Optimized for secure system management, this role performs the following:

- Creates an administrator user with a home directory.
- Configures proper permissions for the administrator’s home directory and associated scripts.
- Deploys SSH `authorized_keys` from `lookup('users', 'administrator').authorized_keys`, leveraging [SSH](https://en.wikipedia.org/wiki/Secure_Shell) best practices.
- Grants [sudo](https://en.wikipedia.org/wiki/Sudo) privileges to the administrator user with password authentication using a dedicated sudoers file.

## Cosmos

The diagram places Administrator User in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [user-administrator 💻]
        svc_administrator["administrator"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The primary purpose of this role is to provide a secure and dedicated administrator account solely for running local administration tasks. This approach minimizes security risks associated with using the root account and enforces best practices in user privilege management.

Requiring at least one SSH public key ensures that the administrator account is always accessible via secure, key-based authentication and avoids insecure or unusable configurations.

## Features

- **User Creation:** Establishes an administrator user with a home directory and generated SSH keys.
- **Home Directory Configuration:** Sets secure permissions on the administrator’s home directory and script folder.
- **SSH Authorized Keys:** Deploys keys from `lookup('users', 'administrator').authorized_keys` (**SPOT-only, must contain at least one key**).
- **Sudo Privileges:** Deploys a dedicated sudoers configuration to grant the administrator user [sudo](https://en.wikipedia.org/wiki/Sudo) rights with password prompt.
- **Modular Integration:** Integrates with common routines and roles to further enhance system security.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
