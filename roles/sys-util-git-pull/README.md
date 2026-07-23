# System Utility: Git Pull (Shallow & Pinned)

## Description

This Ansible role provides a **robust, reusable Git pull utility** for system automation.
It performs shallow clones or updates of Git repositories and optionally **pins the working tree
to a specific tag** (e.g. `stable`) in a detached HEAD state.

The role is designed to solve common automation pitfalls such as:

- conflicting local tags (`would clobber existing tag`)
- detached HEAD updates
- annotated vs. lightweight tags
- reliable change detection for Ansible

Internally, the role delegates complex Git logic to a small, well-tested Python helper script,
keeping the Ansible YAML concise and readable.

---

## Overview

This role:

- Ensures a repository exists at a given destination
- Clones the repository shallowly if it does not exist
- Updates an existing repository in a **detached-safe** manner
- Optionally removes conflicting local tags before fetching
- Optionally pins the checkout to a specific tag (e.g. `stable`)
- Marks the Ansible task as `changed` if:
  - the repository was cloned
  - tags were removed
  - the pinned tag appeared for the first time
  - the pinned tag moved on the remote (optional)

---

## Cosmos

The diagram places System Utility: Git Pull (Shallow & Pinned) in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-util-git-pull 💻]
        svc_util_git_pull["util-git-pull"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to provide a **generic, reusable Git pull primitive**
for other roles in the Infinito.Nexus ecosystem.

Typical use cases include:

- installing tools pinned to a `stable` tag
- reproducible system deployments
- CI/CD-friendly shallow clones
- avoiding fragile inline Git shell logic in roles

---

## Features

- **Shallow Clone & Update** (`--depth`)
- **Detached-safe Branch Updates**
- **Optional Tag Pinning** (e.g. `stable`)
- **Annotated Tag Support** (`tag^{}`)
- **Local Tag Conflict Healing**
- **Deterministic `changed_when` Semantics**
- **Verbose Debug Logging (stderr-only)**

---

## Design Notes

- All human-readable logs go to **stderr**
- Machine-readable state (`CHANGED=…`) is written to **stdout**
- This guarantees reliable `changed_when` behavior in Ansible
- The Python helper is intentionally self-contained and unit-testable

---

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
