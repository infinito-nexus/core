# pgAdmin

## Description

pgAdmin is the most popular and feature‑rich open source administration and development platform for PostgreSQL. This deployment provides a secure, containerized pgAdmin instance complete with optional OAuth2 proxy support for enhanced authentication. It is built for both developers and database administrators who want an easy‐to‐use web interface to manage multiple PostgreSQL servers.

## Overview

This Docker Compose deployment uses Ansible automation to launch pgAdmin together with necessary network and volume configurations. It enables you to centrally manage your PostgreSQL databases with the following core software features:

- **Intuitive Web UI:**  
  Access a modern, responsive, and highly customizable dashboard to manage your PostgreSQL servers.
  
- **Multi‑Server Management:**  
  Connect to and administer multiple PostgreSQL instances from a single interface.
  
- **Optional OAuth2 Integration:**  
  Secure your pgAdmin access by integrating an external OAuth2 provider.
  
- **Robust Connectivity:**  
  Easily manage database configurations, user accounts, and monitor query activity with built‑in health checks.

- **Flexible Configuration:**  
  Adjust settings such as SSL options, port numbers, and server credentials through environment variables and templated configuration files.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Other Resources

- [pgAdmin Official Homepage](https://www.pgadmin.org/)
- [pgAdmin Documentation](https://www.pgadmin.org/docs/)

## Persona contract opt-outs

pgAdmin's own login id is the account e-mail `PGADMIN_DEFAULT_EMAIL` ([`templates/env.j2`](./templates/env.j2), [`vars/main.yml`](./vars/main.yml)), not the Keycloak `administrator` username, so the `administrator` persona has no in-app credential once it is through the oauth2-proxy. [`meta/services.yml`](./meta/services.yml) additionally admits only the `web-app-pgadmin` administrator RBAC group to that proxy (`sso.oauth2.allowed_groups`), and `biber` carries an empty role list, so it is denied before pgAdmin is reached. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the `guest` persona and the baseline assertions run unconditionally.
