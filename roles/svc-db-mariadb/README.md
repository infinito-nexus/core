# MariaDB

## Description

The Docker MariaDB Role offers an easy and efficient way to deploy a MariaDB server inside a Docker container. Manage your data securely and effectively, making it ideal for production or local development.

## Overview

This Ansible role facilitates the deployment of a MariaDB server using Docker. It is designed to ensure ease of installation and configuration, with the flexibility to adapt to different environments.

## Features

- **Dockerized MariaDB**: Leverages Docker for MariaDB deployment, ensuring consistency across different environments.
- **Customizable Settings**: Allows customization of the MariaDB instance through various Ansible variables.
- **Network Configuration**: Includes setup of a dedicated Docker network for MariaDB.
- **Idempotent Design**: Ensures that repeat runs of the playbook do not result in unwanted changes.
- **Security Focused**: Implements best practices for securing the MariaDB root password.

## Prerequisites

Before using this role, ensure you have the following:

- Ansible installed on the control machine.
- Docker installed on the target host(s).
- Access to the target host(s) via SSH.

## Configuration

Configure the role by setting the required variables. These can be set in the playbook or in a separate variable file:

- `central_mariadb_root_password`: The root password for the MariaDB server.
- `database_name`: The name of the initial database to create.
- `database_username`: The username for the database user.
- `database_password`: The password for the database user.

## Contributing

Contributions to this project are welcome. Please submit issues and pull requests with your suggestions.

## Further Resources

- [Reset Password for MariaDB/MySQL in Docker](https://wolfgang.gassler.org/reset-password-mariadb-mysql-docker/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
