# Docker Compose Certificate Sync Service

## Description

Keeps Docker Compose services updated with fresh Let’s Encrypt certificates via a systemd oneshot service and timer.

## Overview

Installs a small script and a systemd unit that copy certificates into your Compose project and trigger an NGINX hot-reload (fallback: restart) to minimize downtime.

## Features

- Automatic certificate sync into the Compose project
- Mailu-friendly filenames (`key.pem`, `cert.pem`)
- NGINX hot-reload if available, otherwise restart
- Runs on a schedule you define

## Further Resources

- [Wildcard Certificate Setup (SETUP.md)](./SETUP.md)
- [Role Documentation](https://s.infinito.nexus/code/tree/main/roles/sys-ctl-mtn-cert-deploy)
- [Issue Tracker](https://s.infinito.nexus/issues)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
