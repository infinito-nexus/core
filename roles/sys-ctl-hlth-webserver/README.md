# Webserver Health Check

## Description

This role verifies that each NGINX-served domain returns an expected HTTP status code (200, 301, etc.) and alerts on deviations.

## Overview

The role scans NGINX server block `.conf` files for domains, HEAD-requests each domain, compares the response against per-domain expected codes, and reports mismatches via `sys-ctl-alm-compose`. It is scheduled via a systemd timer for periodic health sweeps. Include this role and define `on_calendar_health_NGINX`. The role installs `requests` via `pip` automatically.

## Features

- **Domain Detection:** Scans NGINX server block `.conf` files for configured domains.
- **HTTP Status Verification:** HEAD-requests each domain and compares the response against per-domain expected codes.
- **Alerting:** Reports mismatches via `sys-ctl-alm-compose`.
- **Scheduled Execution:** Integrates with a systemd timer for periodic health sweeps.

## Further Resources

- [NGINX documentation](https://nginx.org/en/docs/)
- [Ansible uri_module](https://docs.ansible.com/ansible/latest/modules/uri_module.html)
