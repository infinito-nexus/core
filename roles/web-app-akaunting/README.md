# Akaunting

> **End of life.** Infinito.Nexus neither maintains nor tests this role, because
> the deployment can neither auto-provision it nor drive it through a test: since
> Akaunting 3.1 every create is gated behind `api.akaunting.com/plans/limits`,
> which answers 403 without an account API key, so no invoice, customer or user
> can be created unattended. The default `INFINITO_LIFECYCLES` envelope keeps the
> role out of every CI round. Use [ERPNext](../web-app-erpnext/README.md) or
> [Odoo](../web-app-odoo/README.md) instead; both cover the same ledger,
> invoicing and contact surfaces and pin the version they run. Deploy it at your
> own risk and take support from [akaunting.com](https://akaunting.com).

## Description

This Ansible role sets up and manages Akaunting, an innovative online accounting software, using Docker and Docker Compose. Empower your financial management with Akaunting, a dynamic and feature-rich accounting platform designed to simplify your bookkeeping and boost your business growth. Enjoy intuitive tools, real-time insights, and an energetic approach to your finances.

For detailed administration and troubleshooting, see [Administration.md](./Administration.md).

## Overview

This role provides a comprehensive Dockerized environment for running Akaunting. It deploys the Akaunting application alongside a MariaDB database, configures environment variables, and integrates with NGINX as a reverse proxy. This setup is ideal for both production and development environments.

### Key Features

- **Complete Dockerized Deployment**: Uses Docker Compose to run Akaunting and its associated database.
- **Environment Configuration**: Automatically creates and configures the necessary environment files.
- **NGINX Integration**: Sets up NGINX for handling domain-specific requests and SSL termination.
- **Manual Update and Log Access**: Provides guidance for viewing logs, accessing containers, and performing manual updates.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
