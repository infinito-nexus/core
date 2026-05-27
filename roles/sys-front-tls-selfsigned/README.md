# sys-front-tls-selfsigned

## Description

Self-signed TLS provider for sys-front-tls (SAN aware).

## Overview

This role self-signed TLS provider for sys-front-tls (SAN aware). Generates and stores self-signed certificates.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Inputs

- tls_domain
- application_id
- tls_selfsigned_base
- tls_selfsigned_days
- tls_selfsigned_key_bits
- tls_selfsigned_subject (C/O/OU/CN)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
