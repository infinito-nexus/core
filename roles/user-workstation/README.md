# Workstation User

## Description

This role creates the workstation user defined by *WORKSTATION_USER* and configures
its basic environment. It integrates with the shared `user` role to deploy shell
dotfiles and SSH `authorized_keys`.

## Overview

This role creates the workstation user selected via WORKSTATION_USER and configures the user environment.

## Cosmos

The diagram places Workstation User in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [user-workstation 💻]
        svc_workstation["workstation"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## User data resolution

User data must be defined under `users.<name>` and selected via `WORKSTATION_USER`.

Minimum required fields:

- `WORKSTATION_USER`
- `users.<WORKSTATION_USER>.username` (defaults to WORKSTATION_USER if missing)

Optional fields:

- `users.<WORKSTATION_USER>.uid`
- `users.<WORKSTATION_USER>.gid`
- `users.<WORKSTATION_USER>.shell`
- `users.<WORKSTATION_USER>.groups` (list)
- `users.<WORKSTATION_USER>.authorized_keys` (list; may be empty)

## Notes

- Sudo can be enabled via `user_workstation_enable_sudo`.
- Password handling is intentionally conservative. If you want a password, set
  `users.<WORKSTATION_USER>.password` (plain) and enable `user_workstation_set_password`.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
