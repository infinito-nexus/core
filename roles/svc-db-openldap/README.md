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
- **Profile Attributes:** The auxiliary class `infinitoUser` allows the country, phonetic name and time zone attributes that `inetOrgPerson` lacks, so Keycloak can write the full profile back to the directory.
- **Login-Named Entries:** Every user entry is `uid=<username>`, so it holds one `uid`. On an existing host the next deploy moves the entry of a user whose inventory key differs from its username (the platform administrator) to that DN and repoints its group values; XWiki keeps the profile page it created under the old name.
- **Directory Editor ACL:** Members of the `web-app-lam` and `web-app-phpldapadmin` administrator groups get write access to the data tree, `userPassword` included, so LAM and phpLDAPadmin can set and reset passwords; a changed ACL is applied to an existing directory as well.

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

## Public LDAPS

`services.openldap.network.public: true` opens LDAPS on `ports.public.ldaps` (636) through the stream module of openresty, which terminates TLS with the certificate of the role's domain and relays plain LDAP to slapd:

- In compose, openresty runs on the host network and relays to the port OpenLDAP publishes on the loopback (`ports.local.ldap`).
- In swarm, OpenLDAP publishes no port. Its overlay declares `stream_relay` in `meta/networks.yml`, so openresty and OpenLDAP share the network `openldap-relay` on its pinned subnet and no other role joins it. Openresty publishes 636 in host mode on its node and relays to `openldap:<ports.internal.ldap>`, which the resolver of `stream{}` looks up per connection. The relay leaves the openldap overlay and the trusted proxy addresses of the LDAP clients as they are.

Until the swarm path has its live proof, a swarm deploy with the switch on stops: this role right after its run-once flag, and every other role as soon as it looks up the networks of openresty or OpenLDAP, openresty itself and every proxied application included.

## Email Addresses

The inventory address only seeds an entry: a deploy writes it into `mail` of an entry that holds no `mail` and never changes an address the entry already holds. A changed inventory `email` therefore does not reach an existing user. Change an existing user's address in the Keycloak console, or in the directory through LAM or phpLDAPadmin.

Under the `mailbox` email policy of `web-app-keycloak`, the deploy applies the mailbox layout to every entry. It attaches `infinitoMailboxUser`, keeps the current `mail` of an entry as its `infinitoSecondaryMail` when that address lies outside `DOMAIN_PRIMARY` and the entry holds no secondary address yet, and then sets `mail` to `<uid>@<DOMAIN_PRIMARY>`. An entry without a kept address gets the inventory address as secondary address, which is seeded the same way, once.

## Developer Notes

For the LDAP variable tree, DN layout, attribute SPOT, and the rules for pairing LDAP attributes with OIDC claims, see [ldap.md](../../docs/contributing/design/iam/ldap.md).

## Further Resources

- [Bitnami OpenLDAP](https://hub.docker.com/r/bitnami/openldap)
- [phpLDAPadmin Documentation](https://github.com/leenooks/phpLDAPadmin/wiki/Docker-Container)
- [LDAP Account Manager](https://github.com/LDAPAccountManager/docker)
- [RBAC Wikipedia](https://de.wikipedia.org/wiki/Role_Based_Access_Control)
