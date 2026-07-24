# SSH Agent

## Description

[SSH (Secure Shell)](https://en.wikipedia.org/wiki/Secure_Shell) is a cryptographic network protocol for operating network services securely over an unsecured network. The [OpenSSH](https://www.openssh.com/) project provides the reference implementation, including `ssh-agent` for managing authentication keys.

## Overview

This role is intended for Manjaro/Arch systems where `gnome-keyring` no longer reliably manages `ssh-agent` due to changes in behavior under Wayland. It works by deploying a `systemd --user` service, making SSH Agent integration predictable and independent of graphical environment quirks.

## Cosmos

The diagram places SSH Agent in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_desk_git["desk-git 💻 ⚙️"]
    end
    subgraph role [desk-ssh 💻]
        svc_ssh["ssh"]
    end
    dep_desk_git -- "1:1" --> svc_ssh
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to automate the provisioning of SSH agent capabilities and synchronize the `.ssh` directory from a Git repository. This enables users to access private repositories or authenticate with remote servers immediately after login.

## Features

- **Clones a remote SSH config repository** into `~/.ssh` using the `desk-git` role.
- **Deploys and enables a systemd user service** for `ssh-agent`.
- **Ensures environment compatibility** by injecting the `SSH_AUTH_SOCK` variable into either `.bash_profile` or `.profile`.
- **Fails gracefully** with an optional debug message if the Git repository is unreachable.
- **KeePassXC ready**: Ensures compatibility with password managers that support SSH agent integration.

## Quick Setup

### Development

Clone, set up the workstation, and deploy SSH Agent onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-ssh full_cycle=false
```

### Production

Install SSH Agent directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-ssh
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"
INVENTORY=inventories/production
infinito administration inventory provision "$INVENTORY" \
  --inventory-file "$INVENTORY/devices.yml" \
  --host localhost \
  --include "$APP" \
  --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}"
infinito administration deploy dedicated "$INVENTORY/devices.yml" \
  --password-file "$INVENTORY/.password" \
  --diff -vv
```

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
