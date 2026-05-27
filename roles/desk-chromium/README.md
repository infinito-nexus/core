# Chromium

## Description

This Ansible role installs and configures the Chromium browser along with essential security and productivity extensions. It ensures that Chromium is installed and properly set up with forced installation of uBlock Origin and the KeePassXC browser extension via Enterprise Policies, providing a secure and streamlined browsing experience.

## Overview

Designed for various Linux distributions, this role manages the installation of the Chromium browser using the system’s package manager. It configures Chromium's managed policies to automatically deploy key browser extensions, ensuring that users always have a secure and consistent environment. This role integrates seamlessly with other system management roles for a holistic deployment.

## Purpose

The purpose of this role is to automate the provisioning of a secure Chromium environment in a consistent and maintainable way. It reduces manual configuration steps and guarantees that critical browser extensions are enforced, making it ideal for both production and personal deployments.

## Features

- **Installs Chromium Browser:** Automatically installs the appropriate Chromium package based on the target system.
- **Installs KeePassXC:** Ensures KeePassXC is installed for secure password management.
- **Enforces Browser Extensions:** Configures Chromium Enterprise Policies to force-install uBlock Origin and the KeePassXC browser extension.
- **Cross-Platform Support:** Handles package variations for multiple Linux distributions.
- **Seamless Integration:** Provides a stable and secure browsing setup as part of broader system automation workflows.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
