# Qdrant

## Description

This Ansible role deploys and configures a Qdrant vector database in a Docker container using Docker Compose. It runs Qdrant as a central, pinned engine that many application roles share over the cross-stack network, keeping the consumer roles stateless and NFS-shareable in swarm.

## Overview

Built for environments that demand reliability and ease of management, this role:

- Sets up a dedicated Docker network for Qdrant.
- Deploys a Qdrant container with secure configurations and an HTTP readiness healthcheck.
- Provides a connection lookup (`engine`) so consumers resolve the central instance and their own per-consumer collection prefix.

## Purpose

The purpose of this role is to provide an effortless way to deploy a Qdrant vector database via Docker. It minimizes manual interventions while ensuring that the engine is configured securely and reliably for both production and development scenarios.

## Features

- **Automated Deployment:** Installs Qdrant with minimal manual steps.
- **Central Engine:** A single pinned stack shared by many consumers, mirroring the central database roles.
- **Per-Consumer Isolation:** OSS Qdrant has no per-user auth; each consumer is isolated by the collection-name prefix `{entity}_`.
- **Enhanced Security:** The service is bound to `127.0.0.1:6333`, restricting access and enhancing security.
- **Seamless Docker Integration:** Works harmoniously with Docker Compose and other roles in your infrastructure.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
