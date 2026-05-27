# Firefox

## Description

This Ansible role installs and configures Firefox on Arch Linux systems, enforcing Enterprise Policies to automatically install key browser extensions. It ensures that Firefox is installed and set up with policies that force-install uBlock Origin and the KeePassXC Browser extension, delivering a secure and consistent browsing experience.

## Overview

Tailored for Arch Linux, this role handles the installation of Firefox using the system’s package manager (`pacman`). It deploys a `policies.json` file to Firefox’s distribution directory, ensuring that critical extensions are automatically installed via Firefox Enterprise Policies.

## Purpose

The role automates the provisioning of a secure Firefox environment, reducing manual configuration and ensuring consistency across deployments. It is ideal for environments where a standardized and secure browsing setup is required.

## Features

- **Installs Firefox:** Uses `pacman` to install the Firefox package.
- **Enforces Enterprise Policies:** Deploys a `policies.json` file that forces the installation of uBlock Origin and the KeePassXC Browser extension.
- **Streamlined Configuration:** Automatically creates necessary directories and applies correct file permissions.
- **Seamless Integration:** Easily integrates with other automation roles for a complete system setup.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
