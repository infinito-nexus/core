# Dotlinker

## Description

This Ansible role ensures the `doli` (dotlinker) CLI is installed (via `pkgmgr`)
and applies dotlinker mappings provided by the calling role.

The role is intentionally generic: it does not know anything about Nextcloud or other apps.
It can be included multiple times from different roles, each time with a different set of mappings.

## Overview

This role installs and applies dotlinker (doli) mappings (generic role).

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Usage

Call this role via `include_role` and pass mappings through `dotlinker_mappings`:

- `name`: unique mapping id
- `backend`: `cloud` or `chezmoi`
- `src`: source path (original location)
- `dest`: destination path (required for `cloud`)

The role will register mappings using `doli add` and can optionally run `doli pull`.

## Variables

- `dotlinker_user` (required): user to run `doli` as
- `dotlinker_config_path` (default: `~/.config/dotlinker/config.yaml`)
- `dotlinker_cli_name` (default: `doli`)
- `dotlinker_package_name` (default: `doli`)
- `dotlinker_replace` (default: `true`): pass `--replace` to `doli add`
- `dotlinker_apply` (default: `true`): run `doli pull` after adding mappings

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
