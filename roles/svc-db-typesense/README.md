# Typesense

## Description

This Ansible role deploys and configures a central Typesense search engine in a Docker container using Docker Compose. It is designed as a central engine: many application roles share one pinned Typesense stack instead of each embedding its own sidecar, keeping the application roles stateless, unpinned and NFS-shareable in swarm.

## Overview

Built for environments that demand reliability and ease of management, this role:

- Sets up a dedicated Docker network for Typesense.
- Deploys a Typesense container with healthchecks and a bootstrap admin API key.
- Provisions a per-consumer scoped API key (limited to collections prefixed `<entity>_`) over the Typesense `/keys` API, idempotently.

## Purpose

The purpose of this role is to provide an effortless way to run a shared Typesense engine via Docker while giving each consumer its own isolated, scoped credential. It minimizes manual interventions while keeping engine on-disk state node-local (it cannot live on NFS).

## Features

- **Automated Deployment:** Installs Typesense with minimal manual steps.
- **Per-Consumer Isolation:** Issues a scoped API key per consumer, restricted to its own collection namespace.
- **Enhanced Security:** The service is bound to `127.0.0.1:8108`, restricting access and enhancing security.
- **Seamless Docker Integration:** Works harmoniously with Docker Compose and other roles in your infrastructure.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
