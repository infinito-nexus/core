# Java

## Description

Installs OpenJDK 11 (`jdk11-openjdk`) on Pacman-based systems to provide a Java runtime and development environment.

## Overview

This README file is for the Java role, which is part of the `infinito`. The role is specifically designed to automate the installation of Java on a system, focusing on the OpenJDK 11 version.

## Cosmos

The diagram places Java in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [dev-java 💻]
        svc_java["java"]
    end
    subgraph dependents [Dependents]
        dpt_desk_bluray_player["desk-bluray-player 💻 ⚙️"]
    end
    svc_java -- "1:1" --> dpt_desk_bluray_player
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Contents of the role

The `main.yml` file within the `java` role consists of a single, but crucial task:

1. **Install Java**: This task uses the `community.general.pacman` module to install the `jdk11-openjdk` package. It ensures that Java Development Kit 11 (OpenJDK 11) is present on the system.

## Purpose

The primary objective of this role is to provide a straightforward and efficient method for setting up Java, specifically JDK 11, on personal computers or development environments. This setup is essential for developers who work with Java or run applications that require the Java runtime environment.

## Prerequisites

- **Ansible**: You need to have Ansible installed on your system to use this role.
- **Arch Linux-based System**: The role uses the `pacman` package manager, indicating that it is intended for use on systems based on Arch Linux or its derivatives.

## Running the role

To run this role:

1. Clone the `computer-role` repository to your system.
2. Navigate to the `roles/java` directory within the repository.
3. Execute the role using Ansible. Make sure you have the necessary permissions to install packages on your system.

## Customization

This role is focused on installing JDK 11, but it can be easily modified to install different versions of the JDK or additional Java-related tools as per your requirements.

## Support and Contribution

For support, feedback, or contributions to the role, please open an issue or submit a pull request in the `infinito` repository. Contributions that enhance the role or broaden its applicability are greatly appreciated.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
