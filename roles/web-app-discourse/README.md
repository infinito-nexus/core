# Discourse

## Description

Discourse is a popular open-source discussion platform designed to foster community engagement through modern, user-friendly features and robust moderation tools. It creates a dynamic space for discussions, offering seamless notifications and customizable interfaces to keep your community active and engaged.

## Overview

This role deploys Discourse using Docker, automating tasks such as container orchestration, service configuration, and routine administrative operations. It integrates key components like Redis and PostgreSQL, sets up domain routing with NGINX, and ensures streamlined updates for a reliable forum experience.

## Features

- **Modern Forum Experience:** Engage in interactive, real-time discussions with a responsive, mobile-friendly design.
- **Robust Moderation Tools:** Benefit from comprehensive tools for content management and community moderation.
- **Customizable Layouts & Themes:** Tailor your forum’s look and functionality to suit your community’s unique style.
- **Scalable Architecture:** Utilize a Docker-based deployment that adapts easily to increasing traffic and community size.
- **Extensive Plugin Support:** Enhance your forum with a wide range of plugins and integrations for additional functionality.

## Addons

Addons are declared in [`meta/addons/`](./meta/addons/) and read at deploy time via `lookup('config', application_id, 'addons')`.

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| `docker_manager` | plugin | enabled | none |
| `discourse-activity-pub` | plugin | enabled | none |
| `discourse-akismet` | plugin | enabled | none |
| `discourse-ldap-auth` | plugin | follows `services.ldap.enabled` (currently off) | `ldap` |

The `ldap` service block in [`meta/services.yml`](./meta/services.yml) is intentionally pinned to literal `false` (see [TODO.md](./TODO.md)): the `jonmbake/discourse-ldap-auth` plugin breaks Discourse bootstrap on recent versions. `discourse-ldap-auth` therefore resolves to disabled until that block is flipped back to the dynamic group-membership form.

## Further Resources

- [Discourse Official Website](https://www.discourse.org/)
- [Discourse GitHub Repository](https://github.com/discourse/discourse_docker.git)
- [Discourse Meta Forum](https://meta.discourse.org/)
- [Discourse Documentation](https://meta.discourse.org/t/discourse-setup-guide/21966)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
