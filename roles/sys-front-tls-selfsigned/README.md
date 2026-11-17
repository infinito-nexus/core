# sys-front-tls-selfsigned

## Description

Self-signed TLS provider for sys-front-tls (SAN aware).

## Overview

This role self-signed TLS provider for sys-front-tls (SAN aware). Generates and stores self-signed certificates.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Inputs

- domain (the vhost sys-front-tls chose this provider for; TLS and certificate resolve by it)
- application_id
- tls_selfsigned_base
- tls_selfsigned_days
- tls_selfsigned_key_bits
- tls_selfsigned_subject (C/O/OU/CN)
