# RabbitMQ

## Description

This Ansible role provides a central RabbitMQ message broker that many roles share. It runs the broker inside a Docker container and isolates each consumer with its own virtual host and user, making it suitable for production or local development.

## Overview

The central stack (`templates/compose.yml.j2`) runs the `rabbitmq` image with:

- An `admin` user authenticated from the `RABBITMQ_PASSWORD` credential.
- A bind on `127.0.0.1:5672` plus the shared cross-stack overlay network for consumers.
- A built-in `rabbitmq-diagnostics ping` healthcheck.

Per-consumer provisioning (`tasks/02_init.yml`) runs with `application_id=svc-db-rabbitmq` and `database_consumer_id=<consumer>`; it resolves the consumer's vhost name, username and password via `lookup('engine', 'rabbitmq', <consumer>, ...)` and reconciles an idempotent vhost, user and `set_permissions` grant scoped to that vhost. Existing vhosts and users are skipped, and the consumer password is realigned with the inventory on every deploy.

## Features

- **Central broker** one shared RabbitMQ stack consumed by many roles.
- **Vhost isolation** one virtual host per consumer.
- **User isolation** one RabbitMQ user per consumer, granted full permissions only on its own vhost.
- **Idempotent provisioning** vhosts, users and permissions reconciled on every deploy via `rabbitmqctl`.
- **Built-in healthcheck** `rabbitmq-diagnostics ping`.

## Further Resources

- [Official RabbitMQ Docker image on Docker Hub](https://hub.docker.com/_/rabbitmq)
- [rabbitmqctl management documentation](https://www.rabbitmq.com/docs/cli)
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
