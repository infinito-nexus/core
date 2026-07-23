# dev-nix

This role installs the Nix package manager in a **secure, reproducible, and
idempotent** way across multiple Linux distributions.

## Description

The role installs **Nix** using either the native package manager
(where supported and reliable) or the **official installer** with
**SHA256 verification**.

On platforms where distro packages are known to be problematic
(e.g. Arch Linux ARM), the role deliberately avoids the system package
and falls back to the official installer to ensure a working and
up-to-date Nix installation.

## Overview

This role installs the Nix package manager via pacman on Arch x86_64 or via the official installer with SHA256 verification.

## Cosmos

The diagram places dev-nix in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [dev-nix 💻]
        svc_nix["nix"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Installation Strategy

The role automatically selects the appropriate installation method:

- **Arch Linux (x86_64)**  
  Installs `nix` via the system package manager (`pacman`).

- **All other platforms** (including Arch Linux ARM, Debian, Ubuntu, Fedora, EL, Generic Linux)  
  Uses the **official Nix installer** in multi-user (daemon) mode.

This avoids ABI and SONAME mismatches on rolling or less frequently
rebuilt distributions.

## Security Model

The official installer is **downloaded at runtime** and verified before execution:

- The installer script is fetched from the official release location
- Its SHA256 checksum is fetched from the same release
- The checksum is validated **before** execution
- Installation aborts immediately if verification fails

No unverified code is executed on the target system.

## Features

- Automatic platform detection (Arch x86_64 vs others)
- Verified official installer with SHA256 checksum validation
- Multi-user (daemon) installation mode
- Optional shell integration via `/etc/profile.d`
- Optional activation of experimental features (`nix-command`, `flakes`)
- Fully idempotent (safe to run multiple times)
- Distro-agnostic fallback logic

## Configuration Options

Key variables (see `defaults/main.yml`):

- `dev_nix_installer_version`  
  Nix version to install via the official installer.

- `dev_nix_enable_experimental_features`  
  Enable experimental features such as `nix-command` and `flakes`.

- `dev_nix_enable_shell_snippet`  
  Whether to install a profile snippet for automatic environment loading.

## Notes on Offline Usage

This role **does not ship the installer script** and therefore requires
network access during installation.

If a fully offline or air-gapped setup is required, the role can be
extended to use a locally vendored installer script with a pinned
checksum.

## Further Resources

- Nix project: <https://nixos.org>
- Nix releases: <https://releases.nixos.org>
- Infinito.Nexus License: <https://s.infinito.nexus/license>

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
