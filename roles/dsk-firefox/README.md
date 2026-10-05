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

## Addons

Role-level extensions are declared in `meta/addons/` (unified addon contract, requirement 026):

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `ublock-origin` | `extension` | always installed (`required: true`) | none |
| `keepassxc-browser` | `extension` | always installed (`required: true`) | none |

Both extensions are force-installed through Firefox Enterprise Policies; each addon's `config.xpi_url` is read by [`templates/policies.json.j2`](./templates/policies.json.j2) into `policies.Extensions.Install[]`.
They carry no cross-role dependency, so no `bridges:` key is present.

**Playwright exemption:** these are desktop browser extensions with no in-app web surface to drive, so they are exempt from the per-addon Playwright spec (requirement 026, Decision 11).
