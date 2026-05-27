# Nextcloud Client ️

## Description

This Ansible role installs and configures the Nextcloud desktop client on Arch Linux systems. It also manages symbolic links from commonly used user directories (like `Documents`, `Pictures`, etc.) to the respective folders inside a cloud-synced Nextcloud directory. This ensures user data is seamlessly integrated into the synchronized cloud folder.

## Overview

Targeting user environments on Arch Linux (e.g., Manjaro), this role sets up the official `nextcloud-client` and dynamically links key directories from the user's home folder to Nextcloud. This makes it easy to use the Nextcloud client without needing to manually configure folders.

## Purpose

The purpose of this role is to automate the configuration of cloud-integrated user directories by ensuring that common folders like `Downloads`, `Music`, and `Workspaces` are transparently redirected into a centralized cloud structure. This makes it easier to maintain sys-bkp-friendly, cloud-ready setups for homelab and professional workflows.

## Features

- **Installs the Nextcloud Desktop Client:** Uses `pacman` via the `community.general.pacman` module.
- **Symbolic Linking of User Folders:** Maps home folders (e.g., `Documents`, `Videos`, `Workspaces`) into their Nextcloud equivalents.
- **Dynamic Cloud Directory Resolution:** Builds the target cloud directory path from user and cloud variables.
- **Dump Folder Mapping:** Links `InstantUpload` from the cloud to a `~/Dump` folder for quick camera/file access.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
