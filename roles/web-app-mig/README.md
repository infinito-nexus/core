# MIG

This folder contains the Ansible role to deploy the Meta Infinite Graph for Infinito.Nexus.

## Description

This role sets up the [Ansible Meta Infinite Graph](https://github.com/kevinveenbirkenbach/meta-infinite-graph) for Infinito.Nexus. The Meta Infinite Graph visualizes all dependencies and relationships between Infinito.Nexus roles, making the overall infrastructure structure transparent and easy to understand.

## Overview

The Meta Infinite Graph is an essential tool for analyzing, auditing, and maintaining the modular structure of the Infinito.Nexus ecosystem. It provides a clear overview of all roles and how they are interconnected.

## Features

- Automatic deployment of the Meta Infinite Graph web application
- Shows all dependencies and connections between Infinito.Nexus roles
- Useful for documentation and architecture transparency

## Further Resources

- [Meta Infinite Graph Homepage](https://github.com/kevinveenbirkenbach/meta-infinite-graph)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2` for the same reason. `meta/services.yml` pins `sso.enabled: false` and `sso.shared: false`: MIG serves the pre-rendered Meta Infinite Graph over its own compose stack and has no login surface, no accounts, and no authenticated state at all. Consequently the env file renders no `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `BIBER_USERNAME` or `BIBER_PASSWORD` for the shared helpers to read.

The `dashboard` service in `meta/services.yml` is only a consumer tile pointing at MIG's canonical domain; it does not host MIG. The role's contract is fully carried by the reachability, canonical-domain and content-type scenarios in `files/playwright/playwright.spec.js`, plus the guest persona. The path back to the generic personas is an authenticated MIG surface, which upstream does not have.
