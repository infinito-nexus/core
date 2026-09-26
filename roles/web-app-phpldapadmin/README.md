# phpldapadmin

## Description

phpLDAPadmin is a web‑based LDAP client that provides an intuitive interface for managing LDAP directories. This containerized deployment leverages Docker Compose and Ansible automation to offer a secure, configurable environment for administering and exploring your LDAP configurations.

## Overview

This deployment simplifies LDAP management by presenting a modern web interface that lets you search, modify, and manage directory entries easily. It supports integration with external LDAP servers and works seamlessly behind a reverse proxy, allowing administrators to focus on core directory tasks rather than deployment intricacies.

## Features

- **Web‑Based LDAP Management:**  
  Enjoy an intuitive and responsive interface to browse and administer your LDAP directories.

- **Secure Reverse Proxy Setup:**  
  Easily configure your access through a reverse proxy to ensure secure, controlled entry to your LDAP management tool.

- **Docker Compose Integration:**  
  Benefit from a streamlined, containerized deployment process that simplifies updates and environment configuration.

- **Flexible Environment Configuration:**  
  Customize your installation using environment variables and templated configuration files to match your infrastructure needs.

## Other Resources

- [phpLDAPadmin Docker Container Documentation](https://github.com/leenooks/phpLDAPadmin/wiki/Docker-Container)
- [Official phpldapadmin Homepage](https://github.com/leenooks/phpLDAPadmin)

## Persona contract opt-outs

phpLDAPadmin authenticates with an LDAP bind DN and the OpenLDAP `administrator_database_password`, not with the Keycloak `administrator` username/password pair, so the `administrator` persona has no in-app credential once it is through the oauth2-proxy. [`meta/services.yml`](./meta/services.yml) additionally admits only the `web-app-phpldapadmin` administrator RBAC group to that proxy (`sso.oauth2.allowed_groups`), and `biber` carries an empty role list, so it is denied before phpLDAPadmin is reached. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the `guest` persona and the baseline assertions run unconditionally.
