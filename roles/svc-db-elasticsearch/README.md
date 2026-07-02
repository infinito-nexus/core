# Elasticsearch

## Description

This Ansible role deploys and configures a central Elasticsearch search engine in a Docker container using Docker Compose. It is designed to simplify search administration by automating the creation of networks, containers, and per-consumer index namespaces (a role and user scoped to `<entity>-*` indices) for a secure and high-performance environment.

## Overview

Built for environments that demand reliability and ease of management, this role:

- Sets up a dedicated Docker network for Elasticsearch.
- Deploys a single-node Elasticsearch container with minimal security and automated healthchecks.
- Automates per-consumer provisioning (index-scoped role, user, and namespace) to streamline your workflows.

## Purpose

The purpose of this role is to provide an effortless way to deploy a central Elasticsearch engine via Docker so that application roles stay stateless, unpinned and NFS-shareable in swarm while the engine keeps its on-disk index state node-local. See [docs/architecture/central-engines.md](../../docs/architecture/central-engines.md).

## Features

- **Automated Deployment:** Installs Elasticsearch with minimal manual steps.
- **Per-Consumer Isolation:** Each consumer gets a role and user scoped to its own `<entity>-*` index namespace.
- **Enhanced Security:** The service is bound to `127.0.0.1:9200`, restricting access and enhancing security.
- **Seamless Docker Integration:** Works harmoniously with Docker Compose and other roles in your infrastructure.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
