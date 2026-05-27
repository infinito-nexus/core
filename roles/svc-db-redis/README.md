# Redis

## Description

This Ansible role provides a Jinja2 snippet to inject a Redis service definition into your Docker Compose setup. It renders a `service.yml.j2` template that defines a `redis` container with sensible defaults.

## Overview

The role’s `service.yml.j2` template includes:

- An Alpine-based Redis image (`redis:alpine`)
- Container naming based on `application_id` (defaults to `redis`)
- Restart policy

- Journald logging driver
- A named volume (`redis:/data`) for persistence
- A basic healthcheck using `redis-cli ping`
- Attachment to the default network

Include this snippet in your top-level `compose.yml.j2` where you want Redis to appear.

## Features

- **Configurable `application_id`**  
  Sets container name (`{{ application_id }}-redis`).

- **Restart policy**  
  Controlled by `DOCKER_RESTART_POLICY`.

- **Journald logging**  
  Ensures logs are captured by systemd’s journal.

- **Persistent storage**  
  Declares and mounts `redis:/data`.

- **Built-in healthcheck**  
  Uses `redis-cli ping` with configurable intervals and retries.

## Further Resources

- [Official Redis Docker image on Docker Hub](https://hub.docker.com/_/redis)  
- [Ansible Jinja2 documentation](https://docs.ansible.com/ansible/latest/user_guide/playbooks_templating.html)  
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/)  

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
