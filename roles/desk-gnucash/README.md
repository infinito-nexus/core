# GnuCash

## Description

Installs GnuCash finance management software on Pacman-based systems, ensuring the latest version is present.

## Overview

This Ansible role is responsible for installing GnuCash, a free and open-source financial management software, on systems utilizing the Pacman package manager. It's particularly useful for setting up GnuCash in a Linux environment with minimal manual intervention.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Role: desk-gnucash

The `desk-gnucash` role ensures that GnuCash is installed and maintained at its latest available version in the Pacman repositories.

## Requirements

- Target systems should be running a Linux distribution that uses the Pacman package manager.
- Ansible should be installed and configured on the system initiating the playbook.

## Role Tasks

- `main.yml`: The main task file that handles the installation of GnuCash.

### Task Details

- **Install GnuCash**: This task uses the `community.general.pacman` module to install GnuCash from the Pacman repositories.

## Usage

To use this role, include it in your playbook and run the playbook using the Ansible command. Ensure that your target systems are accessible and properly configured for Ansible automation.

## Example Playbook

An example of how to use this role in your playbook:

```yaml
- hosts: your_target_group
  roles:
    - desk-gnucash
```

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
