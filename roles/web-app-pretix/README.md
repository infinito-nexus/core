# Pretix

## Description

Simplify event management with **Pretix**, an open-source ticketing system for conferences, workshops, and cultural events. Pretix empowers organizers with flexible ticket sales, attendee management, and secure payment integrations, all under your control.

## Overview

This role deploys Pretix using Docker, automating the installation, configuration, and management of your Pretix server. It integrates with an external PostgreSQL database, Redis for caching and sessions, and an NGINX reverse proxy. The role supports advanced features such as global CSS injection, Matomo analytics, OIDC authentication, and centralized logout, making it a powerful and customizable solution within the Infinito.Nexus ecosystem.

## Features

- **Pretix Installation:** Deploys Pretix in a dedicated Docker container.  
- **External PostgreSQL Database:** Configures Pretix to use a centralized PostgreSQL service.  
- **Redis Integration:** Adds Redis support for caching and session handling.  
- **NGINX Reverse Proxy Integration:** Provides secure access and HTTPS termination.  
- **OIDC Authentication:** Seamless integration with identity providers such as Keycloak.  
- **Centralized Logout:** Unified logout across applications in the ecosystem.  
- **Matomo Analytics & Global CSS:** Built-in support for analytics and unified styling.  

## Further Resources

- [Pretix Official Website](https://pretix.eu/)  
- [Pretix Documentation](https://docs.pretix.eu/en/latest/)  
- [Pretix GitHub Repository](https://github.com/pretix/pretix)  

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
