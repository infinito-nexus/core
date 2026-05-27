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

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
