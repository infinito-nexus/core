# sys-front-tls

## Description

Generic TLS orchestrator that can be plugged in front of any web app reverse proxy.

## Overview

Provide a unified interface for certificates and protocol selection, so application roles
can switch TLS mode without touching app logic.

Supported modes (resolved outside or passed in):

- letsencrypt  -> use (and if missing: issue) Let's Encrypt certs
- self_signed  -> generate and store a self-signed certificate (SAN aware)
- off          -> no TLS, HTTP only

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
