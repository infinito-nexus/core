# sys-svc-compose-ca

## Description

Internal helper role that installs CA-trust injection assets used by Docker
Compose stacks. It ships a small wrapper plus the `inject` script and
validates that the project CA certificate is present on the host before
container builds rely on it.

## Overview

This role installs CA trust injection assets for compose (wrapper + inject
script) and validates CA cert presence.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
