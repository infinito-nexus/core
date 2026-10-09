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
- **Handlers for Runtime Control:** Automatically builds, sets up, or restarts containers based on handlers. Notify `compose up` when rendered files or the service spec changed; notify `container recreate` when only in-container or in-database state changed and the process must reload it — the latter force-recreates in compose mode and forces a task recreation in swarm mode, where `docker stack deploy` alone would leave the running task untouched.
- **Template-ready Service Files:** Predefined service base and health check templates.
- **Integration Support:** Compatible with `sys-svc-proxy` and other Infinito.Nexus service roles.
