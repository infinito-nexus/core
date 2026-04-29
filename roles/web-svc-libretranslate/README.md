# LibreTranslate

This role deploys **LibreTranslate** as a containerized web service using Docker Compose.
It is designed to integrate seamlessly into the Infinito.Nexus stack, including optional
Redis and database backends, CSP handling, and analytics integration.

## Description

LibreTranslate is an open-source machine translation API that can be self-hosted.
This role provides a standardized, reproducible deployment with optional extensions
such as Redis caching, database persistence, and Matomo tracking.

The role follows Infinito.Nexus conventions:
- container abstraction (`container`, `compose`)
- per-role meta configuration under `meta/services.yml` and `meta/server.yml`
- CSP-aware reverse proxy integration
- optional shared services (database, analytics)

## Overview

- Deployment via Docker Compose
- Stateless by default, with optional stateful backends
- Designed for reverse-proxy setups
- Suitable for internal services, public APIs, or desktop integration
- Compatible with the Infinito.Nexus role and metadata system

## Features

- LibreTranslate service deployment
- Configurable container image and version
- Optional Redis backend
- Optional database backend
- Optional Matomo analytics integration
- CSP configuration support
- Custom JavaScript injection
- Desktop integration toggle
- Health checks via HTTP
- Network and dependency handling via shared system roles

## Configuration

All configuration is handled via `meta/services.yml` (services map at file root) and `meta/server.yml` (server block at file root).

Key sections include:
- `services.libretranslate`: image and version
- `services.redis`: enable Redis backend
- `services.matomo`: enable analytics
- `server.domains`: canonical and alias domains
- `server.csp`:
