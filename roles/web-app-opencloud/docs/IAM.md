# Identity and Access Management 🔐

OpenCloud delegates authentication to the central Keycloak realm and consumes user and group data from the central OpenLDAP directory. Local password login is disabled when `services.oidc.enabled` is true (the default), and accounts are auto-provisioned on first OIDC login.

## OIDC 🪪

- Issuer URL: `{{ OIDC.CLIENT.ISSUER_URL }}`
- Client ID: shared `OIDC.CLIENT.ID` (one Keycloak client per realm covers every web app)
- Username claim: `preferred_username`, mapped to OpenCloud `username`
- Role claim: `groups` (Keycloak group memberships flow into OpenCloud roles)
- Auto-provisioning: enabled via `PROXY_AUTOPROVISION_ACCOUNTS=true`
- Built-in IDP excluded via `OC_EXCLUDE_RUN_SERVICES=idp`

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

Members of the `application_administrators` group (per requirement 004) gain OpenCloud admin rights when they log in.

### Verify LDAP wiring 🩺

```bash
make compose-exec cmd="container exec opencloud opencloud config get ldap"
```

## Federation 🔗

If a Keycloak user is not present in OpenLDAP, OpenCloud auto-provisions the user on first login using the `preferred_username` claim. To keep usernames stable across Nextcloud, OpenCloud, and OpenTalk, all three apps share the same `OIDC.CLIENT.REALM` and the same `LDAP.DN.OU.USERS` source.
