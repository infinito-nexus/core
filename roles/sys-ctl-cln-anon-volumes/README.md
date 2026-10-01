# Cleanup Docker Anonymous Volumes

## Description

This Ansible role installs and executes [`dockreap`](https://github.com/kevinveenbirkenbach/docker-volume-cleaner), a tool designed to clean up unused anonymous Docker volumes (including symlinks and their targets) to maintain a tidy Docker environment.

## Overview

The role installs `dockreap` using Python tooling and runs it with the `--no-confirmation` flag to ensure automatic, non-interactive cleanup.

## Purpose

This role automates the removal of orphaned Docker volumes that consume unnecessary disk space. It is especially useful in backup, CI/CD, or maintenance routines.

## Features

- **Automated Cleanup:** Runs `dockreap --no-confirmation` to remove unused anonymous Docker volumes.
- **Python-based Install:** Installs `dockreap` (isolated, system-friendly CLI install).
- **Idempotent Execution:** Ensures the tool is installed and run only once per playbook run.
- **Symlink-Aware:** Safely handles symlinked `_data` directories and their targets.
