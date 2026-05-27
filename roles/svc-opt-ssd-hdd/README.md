# Storage Optimizer

## Description

This role optimizes storage allocation for Docker volumes by migrating volumes between SSD (rapid storage) and HDD (mass storage) based on container image types. It creates symbolic links to maintain consistent storage paths after migration.

## Overview

The role performs the following tasks:

- Migrates Docker volumes with database workloads to rapid storage (SSD) for improved performance.
- Moves non-database Docker volumes to mass storage (HDD) to optimize storage usage.
- Manages container stopping and restarting during the migration process.
- Creates symbolic links to preserve consistent file paths.

## Purpose

The primary purpose of this role is to enhance system performance by ensuring that Docker volumes are stored on the most appropriate storage medium, optimizing both speed and capacity.

## Features

- **Dynamic Volume Migration:** Moves Docker volumes based on container image types.
- **Symbolic Link Creation:** Maintains consistent access paths after migration.
- **Container Management:** Safely stops and starts containers during volume migration.
- **Performance Optimization:** Improves overall system performance by leveraging appropriate storage media.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
