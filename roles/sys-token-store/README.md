# sys-token-store

## Description

`sys-token-store` is a lightweight Ansible helper role for **resolving and persisting per-user application tokens** in a unified and idempotent way.

It provides a **single source of truth** for application tokens while keeping runtime usage simple and consistent across roles.

The role is intentionally **not a secret generator**.  
It only **stores and propagates tokens that already exist** (e.g. created by bootstrap processes or provided externally).

---

## Overview

This role stores and manages per-user application tokens in a local YAML store file (idempotent read/write helpers).

## Cosmos

The diagram places sys-token-store in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-token-store 💻]
        svc_token_store["token-store"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Core Principles

- **Single logic for all roles**
  - Always resolve tokens as: **`users → token store → empty`**
- **No implicit token generation**
  - Empty tokens are rejected
- **Idempotent persistence**
  - Store file is only rewritten when content actually changes
- **Lookup-based runtime resolution**
  - Tokens are resolved through `lookup('users')`, which hydrates from the store on each lookup call
- **Case-sensitive keys**
  - User keys and application IDs must match exactly

---

## Token Resolution Order

When resolving a token, the following order is used:

1. `lookup('users', '<user>').tokens.<application_id>`
2. Token store file (`tokens.yml`)
3. Empty string (`''`)

No automatic fallback generation happens.

---

## Store Format

Tokens are stored in a single YAML file:

```yaml
users:
  administrator:
    tokens:
      web-app-matomo: "46e50b0eb52d0d141a7d6cf9b3d0b3e2"
```

Default location:

```
/var/lib/infinito/secrets/tokens.yml
```

Permissions are restricted to root by default.

---

## Provided Tasks

### `write.yml`

Persists a token so it is available through the `users` lookup on subsequent reads.

This is the **canonical way** to store tokens.

**Input**

- `sys_token_store_user_key`
- `sys_token_store_app`
- `sys_token_store_token` (must be non-empty)

**Effects**

- Updates the token store file (idempotent)
- Makes the token available via `lookup('users', '<user>').tokens['<app>']`
- Exports `sys_token_store_token`

Empty tokens are rejected explicitly.

---

## Usage Examples

---

### Persist a token

```yaml
- include_role:
    name: sys-token-store
    tasks_from: write.yml
  vars:
    sys_token_store_user_key: administrator
    sys_token_store_app: web-app-matomo
    sys_token_store_token: "{{ matomo_token_value }}"
```

After this, the token is available as:

```yaml
lookup('users', 'administrator').tokens['web-app-matomo']
```

---

## What This Role Does *Not* Do

- ❌ No token generation
- ❌ No encryption
- ❌ No user management
- ❌ No application-specific logic

It is a **generic infrastructure helper**.

---

## Best Practices

- Keep all user and application keys lowercase
- Use stable `application_id` values
- Let application roles create tokens
- Let `sys-token-store` handle persistence

---

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
