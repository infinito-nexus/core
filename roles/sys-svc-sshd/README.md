# sshd

## Description

This Ansible role configures the OpenSSH daemon (`sshd`) by deploying a templated `sshd_config` file. It applies secure, best-practice settings to harden remote access and reduce the risk of misconfiguration or lockout. Settings include disabling root login, enforcing public-key authentication, and setting appropriate logging levels.

## Overview

- Renders `sshd_config.j2` into `/etc/ssh/sshd_config` with customizable options
- Sets file ownership (`root:root`) and permissions (`0644`)
- Automatically reloads and restarts the SSH service via a systemd handler
- Uses a `run_once_sys_svc_sshd` fact to ensure idempotent execution

Key variable: `SYS_SVC_SSHD_PASSWORD_AUTHENTICATION` (default: `false`) enables password authentication when explicitly required by controlled environments such as local E2E test targets.

## Cosmos

The diagram places sshd in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-svc-sshd 💻]
        svc_svc_sshd["svc-sshd"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Templated Configuration:** Delivers a Jinja2-based `sshd_config` with variables for debug logging, PAM support, and password-auth overrides.
- **Security Defaults:** Disables password authentication and root login; enforces public-key authentication; conditionally sets `LogLevel` to `DEBUG3` when `MODE_DEBUG` is true.
- **Systemd Integration:** Handles daemon reload and service restart seamlessly on configuration changes.
- **Idempotency:** Ensures tasks run only once per play by setting the `run_once_sys_svc_sshd` fact.

## Further Resources

- [sshd_config manual](https://man7.org/linux/man-pages/man5/sshd_config.5.html)
- [Ansible Template Module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/template_module.html)
- [Ansible handler best practices](https://docs.ansible.com/ansible/latest/user_guide/playbooks_handlers.html)
- [OpenSSH security recommendations](https://www.openssh.com/security.html)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
