# Database Docker with Web Proxy

## Description

This role builds on `sys-stk-backend` by adding a reverse-proxy frontend for HTTP access to your database service.

## Overview

This role extends sys-stk-backend by adding an HTTP reverse proxy via sys-stk-front-proxy.

## Features

- **Database Composition**  
  Leverages the `sys-stk-backend` role to stand up your containerized database (PostgreSQL, MariaDB, etc.) with backups and user management.

- **Reverse Proxy**  
  Includes the `sys-stk-front-proxy` role to configure a proxy (e.g. NGINX) for routing HTTP(S) traffic to your database UI or management endpoint.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
