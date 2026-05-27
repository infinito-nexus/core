# Repository Architecture 🏗️

This page explains how Infinito.Nexus is put together so contributors know where a change belongs and why the repository is shaped the way it is.

The short version:

- Git is the control plane.
- Ansible decides what should exist.
- Docker Compose runs the service layer.
- Bundles assemble roles into real deployments.
- Make targets expose stable, human-facing commands.
- Docs keep humans and AI agents aligned.

## What This Repository Actually Is 🤔

Infinito.Nexus is not one application. It is a repository of building blocks for deploying, operating, and maintaining self-hosted systems.

The architecture is built around one simple idea: keep the parts small, explicit, and reusable, then combine them into a full stack only when a bundle needs them.

## The Building Blocks 🧱

### Roles 📦

Roles are the smallest meaningful unit.

A role usually owns one capability:

- `sys-*` for host setup, OS tuning, cleanup, certificates, and maintenance
- `svc-*` for shared services such as databases, proxies, mail, DNS, VPN, backups, and identity support
- `web-app-*` for end-user applications
- `dev-*` for development tooling
- `desk-*` for workstation setup
- `web-svc-*` and `web-opt-*` for web-facing helpers and redirects

For example, `web-app-nextcloud` owns the Nextcloud deployment, `sys-svc-webserver-https` owns the HTTPS plumbing, and `sys-ctl-cln-docker` handles Docker cleanup.

A role MUST be able to answer four questions clearly:

- What does it install or configure?
- What is optional?
- What does it depend on?
- How is it turned off?

If a role cannot answer those questions, it is probably doing too much.

### Bundles and Inventories 🗂️

Bundles are the assembly layer.

[inventories/bundles/servers/](../../../inventories/bundles/servers) describe concrete deployment shapes such as a personal server, a community hub, or a sovereign cloud setup. They decide which roles are active together and which ones stay out.

For example, the repository already has server bundles such as `community-hub`, `personal-nexus`, and `sovereign-cloud`. Each one combines the same building blocks in a different way for a different operating model.

That means the bundle is not where logic lives. It is where the architecture becomes a real deployment.

### Runtime ⚙️

Most application roles use Docker Compose for the running services.

That separation matters:

- Ansible prepares the host and renders the desired state.
- Compose starts the application containers.
- The role keeps the app-specific wiring close to the app.
- The host stays responsible for host-level concerns.

That is why you will find host work in `sys-*` roles and app work in `web-app-*` roles instead of one giant deployment script.

### Entry Points 🚪

People and CI MUST interact with the repo through stable commands, not through improvised command sequences.

The main entry points are:

- [Makefile](../../../Makefile)
- [scripts/](../../../scripts/)
- [tests/](../../../tests/)
- [lint.md](../actions/testing/lint.md)
- [testing.md](../actions/testing.md)
- [docs/contributing/](../../)

Those layers keep local development, CI, and production behavior closer together.

## Why The Architecture Looks Like This 🤔

### Composition Over Monolith 🔧

The repository prefers many focused parts over one giant playbook.

Why:

- smaller diffs
- easier reviews
- safer rollbacks
- more reuse across bundles
- less accidental coupling

### Integration Over Forced Migration 🔗

This platform tries to connect existing services instead of demanding a full rewrite.

That is why the repo has:

- proxy roles
- IAM roles
- backup and cleanup roles
- DNS and TLS helpers
- encryption support
- application-specific glue code

The idea is to fit into existing environments instead of replacing everything at once.

### Security By Default 🔒

Security is not a separate project here; it is part of normal composition.

The common pieces are:

- TLS through reverse proxy roles
- centralized identity through LDAP and SSO roles
- secrets through Ansible Vault
- VPN and network exposure controls
- optional full-disk encryption via [hetzner-arch-luks](https://github.com/kevinveenbirkenbach/hetzner-arch-luks)

The point is to make the safe path the natural path.

### Low-Resource Awareness 💡

A good architecture is still usable on smaller machines.

That is why the repo favors:

- enabling only the services you need
- testing one role at a time when possible
- cleanup roles for Docker, disks, and caches
- docs that explain how to scale down the stack

This is not an afterthought. It is part of the design.

### Reversible Changes ↩️

Architectures age well when they make it obvious what can be enabled, disabled, or replaced.

If a service can be removed without rewriting the whole stack, the design is usually healthy.
If removing one part breaks everything else, the boundaries are probably too weak.

## Concrete Examples 💡

### Adding A New Application ➕

A new app MUST:

1. create a `web-app-*` role
2. define its templates and defaults
3. identify shared dependencies such as database, proxy, or identity
4. add it to the relevant bundle
5. document how to deploy, operate, and troubleshoot it

### Introducing A Shared Service 🔧

A new shared service MUST:

1. create the role
2. keep host setup separate from consumer setup
3. expose only the configuration the dependent roles need
4. document the service contract and lifecycle

See [base.md](role/services/base.md) for the full service registration, loading, and injection model.

### Changing An Existing Deployment ✏️

For a normal change, contributors MUST:

1. update the role first
2. update the bundle only if composition changes
3. update docs if the operator workflow changes
4. update tests if the contract changes

If you skip those steps, the repository becomes harder to understand for the next person.

See [workflow.md](../workflow.md) for the full contribution flow.

## What This Architecture Is Not 🚫

- not a single monolithic application
- not a place where one role owns every concern
- not a hidden "just run this shell script" system
- not a repo where docs can drift away from behavior
- not a one-size-fits-all production template

## How To Navigate The Repo 🗺️

If you are trying to understand a change, start here:

- [roles/](../../../roles/) for behavior
- [inventories/bundles/](../../../inventories/bundles/) for deployment shapes
- [Makefile](../../../Makefile) and [scripts/](../../../scripts/) for supported commands
- [lint.md](../actions/testing/lint.md) for code and framework rules
- [base.md](role/services/base.md) for service registration, loading, and injection
- [testing.md](../actions/testing.md) for refactoring, debugging, and testing
- [docs/contributing/](../../) for workflow and constraints
- [tests/](../../../tests/) for the expected contracts

If you can explain a change across those areas, you probably understand the architecture.

## The Core Idea 💡

Infinito.Nexus works best when the pieces stay small, the boundaries stay explicit, and the docs stay honest.
