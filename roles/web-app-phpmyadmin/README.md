# PhpMyAdmin

## Description

This Ansible role deploys [PhpMyAdmin](https://www.phpmyadmin.net/) in a secure Docker environment, complete with optional OAuth2 proxy support. It enables seamless management of MariaDB/MySQL databases via a web-app-based interface.

## Overview

The role configures and deploys a containerized PhpMyAdmin instance using Docker Compose. It optionally integrates with a central database and uses dynamic Ansible variables to support flexible deployments in both production and homelab environments.

## Purpose

The purpose of this role is to provide a reliable, configurable, and secure PhpMyAdmin deployment out-of-the-box. It minimizes the need for manual setup, and integrates smoothly with other Infinito.Nexus infrastructure roles.

## Features

- **Docker Compose Integration:** Deploy PhpMyAdmin via a templated Compose setup.
- **OAuth2 Proxy Support:** Secure your admin interface with modern authentication.
- **Central DB Integration:** Connects to shared MariaDB instances for multi-role environments.
- **Custom Configuration:** Leverage Ansible variables to fine-tune your deployment.
- **Healthchecks & Networking:** Includes Docker healthchecks and network setup logic.

## Persona contract opt-outs

phpMyAdmin signs in as the MariaDB `root` account wired through `PMA_USER` / `PMA_PASSWORD` ([`templates/env.j2`](./templates/env.j2), [`vars/main.yml`](./vars/main.yml)); the Keycloak `administrator` username is not a MariaDB user, so in the `services.sso.enabled: false` matrix variants the `administrator` persona has no native login to drive and [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_ADMINISTRATOR_BLOCKED=true`. [`meta/services.yml`](./meta/services.yml) admits only the `web-app-phpmyadmin` administrator RBAC group to the oauth2-proxy (`sso.oauth2.allowed_groups`) and `biber` carries an empty role list, so `PERSONA_BIBER_BLOCKED=true` holds in every variant. The `guest` persona and the baseline assertions run unconditionally.
