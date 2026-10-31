# Docker Compose

## Description

This Ansible role manages Docker Compose project structures and workflows for applications on Arch Linux. It creates dedicated instance directories, manages `.env` and `compose.yml` files, and provides automation logic for project reset, rebuild, and startup sequences.

Refer to the [Docker Compose documentation](https://docs.docker.com/compose/) and the [Arch Wiki – Docker](https://wiki.archlinux.org/title/Docker) for more details.

## Overview

This role creates a flexible directory layout for managing Docker Compose projects across environments. It ensures directories are initialized, optionally reset, and kept clean using internal flags like `MODE_RESET` or `MODE_CLEANUP`.

## Purpose

To offer a centralized, extensible system for managing containerized applications using Docker Compose within the Infinito.Nexus architecture. The role allows easy integration of services, secrets, configurations, and custom behaviors per application.

## Features

- **Dynamic Directory Structure:** Creates per-application instance folders for Compose setups.
- **Reset Logic:** Cleans previous Compose project files and data when `MODE_RESET` is enabled.
- **Handlers for Runtime Control:** Automatically builds, sets up, or restarts containers based on handlers. Notify `compose up` when rendered files or the service spec changed; notify `container recreate` when only in-container or in-database state changed and the process must reload it — the latter force-recreates in compose mode and forces a task recreation in swarm mode, where `docker stack deploy` alone would leave the running task untouched. To rebuild and recreate single services while the rest of the stack keeps running, set `compose_service_up_targets` to their service keys and notify `compose-service-up`; it acts in compose mode only and recreates a service only when its image or configuration changed.
- **Decommission:** As the last step of a compose deploy without `--id` and with `MODE_CLEANUP`, every compose instance directly below `DIR_COMPOSITIONS` that no active role owns is stopped with `compose down --remove-orphans` and then deleted. Its named volumes stay; bind-mounted data inside the directory, such as `volumes/`, goes with it. A role counts as active when any host of the inventory carries it, when it is in the `CURRENT_PLAY_APPLICATIONS` dependency closure, or when the play prepared its instance. Only a directory named after a known role and carrying the full instance layout (`compose.yml`, `.env/`, `config/`, `services/`, `volumes/`) counts as an instance. An instance that a container outside its compose project is named after, such as a launcher-managed container, stays too. Every directory left alone is listed in the deploy output. The deploy fails before deleting anything when a container still carries the stopped project's name or working directory.
- **Template-ready Service Files:** Predefined service base and health check templates.
- **Integration Support:** Compatible with `sys-svc-proxy` and other Infinito.Nexus service roles.
