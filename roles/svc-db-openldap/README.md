# OpenLDAP

## Description

Unleash the potential of centralized identity management with [OpenLDAP](https://www.openldap.org/). This powerful directory service provides a robust platform for managing users, groups, and organizational units while ensuring secure, scalable, and efficient authentication and authorization.

## Overview

Deploy OpenLDAP in a Docker environment with support for TLS-secured communication via an NGINX stream proxy. OpenLDAP offers advanced directory management capabilities, including flexible schema definitions, dynamic configuration overlays, and comprehensive query support with LDAP search utilities.

## Features

- **Centralized Identity Management:** Maintain a unified repository for all users and groups with robust organizational structures.
- **Flexible Schema Support:** Customize and extend directory schemas to meet diverse organizational requirements.
- **Secure Communications:** Enable TLS encryption for data in transit when accessed through an NGINX reverse proxy.
- **Dynamic Configuration:** Leverage runtime configuration overlays to adjust directory settings without downtime.
- **Comprehensive Query Capabilities:** Utilize LDAP search tools to efficiently query and manage directory data.
- **High Performance and Scalability:** Designed to handle large-scale deployments with rapid lookup and authentication response times.

## User Password Update Policy

By default, LDAP user passwords are updated on every deployment run.

To set a password only once (on initial user creation), set this flag per user:

```yaml
users:
  alice:
    password: "..."
    password_update: false
```

With `password_update: false`, existing LDAP users keep their current password on later runs.

## Developer Notes

For the LDAP variable tree, DN layout, attribute SPOT, and the rules for pairing LDAP attributes with OIDC claims, see [ldap.md](../../docs/contributing/design/iam/ldap.md).

## Further Resources

- [Bitnami OpenLDAP](https://hub.docker.com/r/bitnami/openldap)
- [phpLDAPadmin Documentation](https://github.com/leenooks/phpLDAPadmin/wiki/Docker-Container)
- [LDAP Account Manager](https://github.com/LDAPAccountManager/docker)
- [RBAC Wikipedia](https://de.wikipedia.org/wiki/Role_Based_Access_Control)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
