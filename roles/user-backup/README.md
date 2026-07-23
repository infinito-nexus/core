# User for Backup Provider

## Description

This role sets up a dedicated backup user (`backup`) for performing secure backup operations. It creates the user, configures a restricted SSH environment with a custom `authorized_keys` template and an SSH wrapper script, and grants necessary sudo rights for executing rsync. This configuration helps ensure controlled and secure access specifically for backup processes.

## Overview

The role is a critical component in a secure backup scheme. By isolating backup operations to a dedicated user, it minimizes the risk of unauthorized actions. The role configures the SSH environment so that only specific, allowed commands can be executed, and it sets up passwordless sudo rights for rsync, ensuring smooth and secure backup operations.

## Cosmos

The diagram places User for Backup Provider in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [user-backup 💻]
        svc_backup["backup"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to enhance the security of your backup system by providing a dedicated user with strict command restrictions. This controlled environment limits the potential damage from a compromised backup account while still allowing efficient backup operations.

## Features

- **User Creation:** Creates a dedicated `backup` user with a home directory.
- **SSH Environment Setup:** Establishes a secure `.ssh` directory and deploys a restricted `authorized_keys` file via a Jinja2 template.
- **SSH Wrapper Script:** Implements a custom SSH wrapper that logs and filters incoming SSH commands, enforcing security policies.
- **Sudo Configuration:** Grants passwordless sudo rights for rsync, enabling secure and automated backup transfers.
- **Integration:** Supports seamless integration with your backup infrastructure by limiting the backup user's permissions to only the required commands.

## Other Resources

For more details on how the role works and advanced configuration options, please see the related references below:

- [Ansible Playbooks Lookups](https://docs.ansible.com/ansible/latest/user_guide/playbooks_lookups.html#id3)
- [Restrict SSH to rsync](http://gergap.de/restrict-ssh-to-rsync.html)
- [SSH Command Restrictions via authorized_keys](https://www.thomas-krenn.com/de/wiki/Ausf%C3%BChrbare_SSH-Kommandos_per_authorized_keys_einschr%C3%A4nken)
- [Rsync and sudo integration](https://askubuntu.com/questions/719439/using-rsync-with-sudo-on-the-destination-machine)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
