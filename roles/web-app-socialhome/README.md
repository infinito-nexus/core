# SocialHome

## Description

Deploy **SocialHome**, a federated social network focused on content hubs and federation. This role provides a Docker-based scaffold and domain wiring so you can bring SocialHome into your Infinito.Nexus stack.

## Overview

This role sets up a SocialHome application using Docker Compose with basic domain and port wiring. It follows your standard role layout and prepares the service to run behind your existing reverse proxy. The current version is a scaffold intended to be expanded with database/cache services and app-specific settings.

## Features

- **Dockerized Scaffold:** Baseline Docker Compose integration and role structure to get you started quickly.
- **Domain & Port Wiring:** Integrates cleanly with your central domain/ports configuration.
- **Ready for Federation:** Intended to support ActivityPub-based federation once the application is fully wired.
- **Extensible Configuration:** Room for adding database, cache, worker processes, and environment tuning.
- **Desktop Integration Hooks:** This README ensures inclusion in the Web App Desktop overview.

## Further Resources

- [SocialHome Project](https://socialhome.network/)
- [ActivityPub (W3C)](https://www.w3.org/TR/activitypub/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
