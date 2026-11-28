# Application garbage collection

## Description

Long-running applications leave data behind that they never clean up themselves: leftovers of failed syncs, temporary packs, remote media caches. Left alone, such leftovers fill a disk long before the application's own data does.

## Overview

This role installs a systemd service and a daily timer that run the `garbage_collector.sh` of every application role deployed on the host in `routine` mode.
Application roles register their script through `tasks/utils/install.yml`, which writes one entry per application id below `DIR_GARBAGE_COLLECTOR_MANIFESTS`.
The [disc space cleaner](../sys-ctl-cln-disc-space/README.md) runs the same dispatcher in `pressure` mode when a disk crosses its threshold.
The destructor stage drops the entries of roles no longer active on the host through `tasks/decommission.yml`.
The script contract and the per-role `garbage_collector` declaration are documented in [garbage_collector.sh.md](../../docs/contributing/artefact/files/role/garbage_collector.sh.md).

## Features

- **Backup lock:** The service waits for every backup, repair and optimizer unit before it starts, so a collector never races a live backup.
- **Failure isolation:** A failing application does not stop the others; each failure is named and the run exits non-zero.
- **Per-application timeout:** Every collector is cut off after `SYS_TIMEOUT_CLEANUP_APP`, on the host and inside the container, where a killed `docker exec` client would leave the work running.
- **Swarm aware:** The container is resolved on the node; an application whose task runs elsewhere is skipped with success, and the node that hosts it collects it.
- **Serialized runs:** A lock file keeps the daily run and a pressure run from collecting the same application at once.
