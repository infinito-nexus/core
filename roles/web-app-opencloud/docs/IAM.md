# Identity and Access Management 🔐

OpenCloud delegates authentication to the central Keycloak realm and consumes user and group data from the central OpenLDAP directory. Local password login is disabled when `services.sso.enabled` is true (the default).

## OIDC 🪪

- Issuer URL: `{{ OIDC.CLIENT.ISSUER_URL }}`
- Client ID: shared `OIDC.CLIENT.ID` (one Keycloak client per realm covers every web app)
- Username claim: `OIDC.ATTRIBUTES.USERNAME`, matched against the OpenCloud `username`
- Accounts: read from the directory, `PROXY_AUTOPROVISION_ACCOUNTS=false`
- Built-in IDP excluded via `OC_EXCLUDE_RUN_SERVICES=idp`

### Roles 🛂

`meta/rbac.yml` sets `realm_roles: true`, so Keycloak grants the realm role `web-app-opencloud-<role>` to every `/roles/web-app-opencloud/<role>` group. The container writes `OPENCLOUD_ROLE_ASSIGNMENT` from `vars/main.yml` to `/etc/opencloud/proxy.yaml` at every start, and the proxy then sets the role at every login from `realm_access.roles`. The first matching value wins:

| `realm_access.roles` value | OpenCloud role |
|---|---|
| `web-app-opencloud-administrator` | `admin` |
| `web-app-opencloud-spaceadmin` | `spaceadmin` |
| `web-app-opencloud-guest` | `user-light` |
| `default-roles-<realm>` | `user` |

`GRAPH_ASSIGN_DEFAULT_USER_ROLE=false` leaves every assignment to the proxy. Without SSO, the container removes `proxy.yaml` and the `default` driver gives every account `user`.

### Verify the role mapping 🩺

```bash
make compose-exec cmd="container exec opencloud cat /etc/opencloud/proxy.yaml"
```

### Verify OIDC discovery 🩺

```bash
make compose-exec cmd="container exec opencloud sh -c 'curl -fsS {{ OIDC.CLIENT.DISCOVERY_DOCUMENT }} | head -c 200'"
```

## LDAP 📒

OpenCloud reads users from the central `svc-db-openldap` service.

- URI: `{{ LDAP.SERVER.URI }}`
- Bind DN: `{{ LDAP.DN.ADMINISTRATOR.DATA }}`
- User base DN: `{{ LDAP.DN.OU.USERS }}`
- Group base DN: `{{ LDAP.DN.OU.GROUPS }}`
- User filter: `(objectclass=inetOrgPerson)`
- Group filter: `(objectclass=groupOfNames)`
- Display name: `LDAP.USER.ATTRIBUTES.FULLNAME` through `OC_LDAP_USER_SCHEMA_DISPLAYNAME`

### Verify LDAP wiring 🩺

```bash
make compose-exec cmd="container exec opencloud opencloud config get ldap"
```

## Federation 🔗

To keep usernames stable across Nextcloud, OpenCloud, and OpenTalk, all three apps share the same `OIDC.CLIENT.REALM` and the same `LDAP.DN.OU.USERS` source.
