# Unbound

## Description

This Ansible role deploys a central recursive/forwarding DNSSEC resolver (Unbound) in a Docker container using Docker Compose. It runs as a trivial single-service stack with a static IP on its own network, so consumer stacks can point their `dns:` at it instead of embedding their own resolver.

## Overview

Built as a central engine (mirroring `svc-db-postgres`), this role:

- Sets up a dedicated Docker network for Unbound with a fixed subnet.
- Deploys an Unbound container at a static IP on that network.
- Waits until the resolver answers before consumers are wired to it.

## Purpose

The purpose of this role is to externalise the static-IP DNS resolver out of large multi-service stacks (such as mail) into a single-service stack. Keeping the static-IP allocation in a trivial 1-service / 1-network stack avoids the swarm VIP-allocation deadlock that a 13-service / 4-network stack triggers, and lets consumer roles stay stateless and unpinned.

## Features

- **Central Resolver:** One shared recursive/forwarding DNSSEC resolver for many consumers.
- **Static IP:** Exposes a fixed resolver address on its own network for `dns:` targeting.
- **DinD-aware:** Forwards to public resolvers in nested-Docker/CI where iterative resolution via root-hints is unsupported.
- **Seamless Docker Integration:** Works with Docker Compose and the central-engine deploy machinery.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
