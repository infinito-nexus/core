# Kevins Package Manager

## Description

This Ansible role installs and configures [Kevin's Package Manager](https://github.com/kevinveenbirkenbach/package-manager) - a configurable Python tool designed to manage multiple repositories and automate common Git operations. The role clones the repository from GitHub, sets the executable permissions for the main script, and runs the installation command to set up command aliases.

## Overview

This role automates the deployment of Kevin's Package Manager by:

- Cloning the repository from GitHub.
- Executing the installation command to create/update repository command wrappers.

It ensures that the Package Manager is ready to manage repositories, perform Git operations, and streamline software management tasks.

## Cosmos

The diagram places Kevins Package Manager in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [pkgmgr 💻]
        svc_pkgmgr["pkgmgr"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to simplify the installation of Kevin's Package Manager, reducing manual steps and ensuring a consistent setup across environments. Ideal for developers and system administrators, it helps integrate repository management seamlessly into your automation workflows.

## Features

- **Repository Cloning:** Automatically clones the Package Manager repository from GitHub.
- **Executable Setup:** Sets proper permissions on the main script.
- **Alias Installation:** Runs the installation command to generate command aliases.
- **Configurable Paths:** Allows customization of both the installation and binary directories.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
