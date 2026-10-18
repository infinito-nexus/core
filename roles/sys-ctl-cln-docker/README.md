# Cleanup Docker Resources

## Description

This role performs a complete cleanup of Docker resources by invoking a systemd-managed script.
It removes unused Docker images, stopped containers, networks, build cache, and anonymous volumes.
The cleanup is fully automated and can run on a schedule or be triggered manually.

## Overview

Optimized for maintaining a clean and efficient Docker environment, this role:

* Loads and triggers the anonymous volume cleanup role.
* Installs a systemd service and timer for Docker pruning.
* Deploys a cleanup script that invokes:

  * The anonymous volume cleanup service.
  * `container system prune -a -f` to remove unused Docker resources.
* Allows forced execution during maintenance runs (`MODE_CLEANUP`).

## Purpose

The primary purpose of this role is to prevent storage bloat caused by unused Docker images, volumes, and build artifacts.
Regular pruning ensures:

* Reduced disk usage
* Improved system performance
* Faster CI/CD and container deployments
* More predictable Docker engine behavior

## Features

* **Anonymous Volume Cleanup:** Integrates with `sys-ctl-cln-anon-volumes` to remove stale volumes.
* **Full Docker Prune:** Executes `container system prune -a -f` to reclaim space.
* **Systemd Integration:** Registers a systemd unit and timer for automated cleanup.
* **Scheduled Execution:** Runs daily (or as configured) based on `SYS_SCHEDULE_CLEANUP_DOCKER`.
* **Force Execution Mode:** When `MODE_CLEANUP=true`, cleanup is executed immediately.
* **Safe Execution:** Includes validation for missing services and Docker availability.

## Script Behavior

The cleanup script:

1. Checks whether the anonymous volume cleanup service is defined and available.
2. Starts the service if present.
3. Runs `container system prune -a -f` if Docker is installed.
4. Stops execution immediately on errors (`set -e` behavior).
