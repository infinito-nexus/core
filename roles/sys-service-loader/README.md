# sys-service-loader

## Description

SPOT loader for shared services. Drives the ordered preload pass via
`tasks/main.yml` and the post-load queue flush, plus the shared helper
`tasks/list_or_shoot.yml` used by service roles to route their dependent
roles through the loader's queue.

## Overview

Loader role providing the shared-service preload pass and helper tasks
for queueing post-load role inclusions.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
