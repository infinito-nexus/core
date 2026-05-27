# sys-openssl

## Description

Ensures that the `openssl` CLI is installed on the host.

This role is intended as a shared dependency for other roles that execute
OpenSSL commands on the host system.

## Overview

This role ensures OpenSSL is installed once as a shared host dependency for roles that invoke the `openssl` CLI.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Behavior

- Installs package: `openssl`
- Uses standard Infinito run-once flagging via `run_once_sys_openssl`

## Usage

```yaml
- include_role:
    name: sys-openssl
  when: run_once_sys_openssl is not defined
```

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
