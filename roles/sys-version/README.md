# System Version ️

## Description

This Ansible role extracts the project version from the local `pyproject.toml` (using `playbook_dir`)
and writes it as a system-wide environment variable into `/etc/environment` on the managed host.

## Overview

This role extracts the local pyproject.toml version and writes it as an environment variable in /etc/environment on the target host.

## Features

- Extracts `version = "..."` from `pyproject.toml` on the control node
- Persists the version as an environment variable in `/etc/environment`
- Updates the existing variable idempotently (no duplicates)
- Creates `/etc/environment` if missing

## Variables

- `FILE_ENVIRONMENT` (default: `/etc/environment`)
- `INFINITO_VERSION_ENV_NAME` (default: `INFINITO_VERSION`)
