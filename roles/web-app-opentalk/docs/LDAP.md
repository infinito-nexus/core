# LDAP Integration (Transitive) 📒

OpenTalk does not open LDAP connections itself. It relies on Keycloak's LDAP federation (`svc-db-openldap` is mapped into the central Keycloak realm) and queries Keycloak's admin Web API for user lookups. This avoids dual-source-of-truth problems and keeps LDAP credentials away from the OpenTalk service account.

## Chain 🔗

1. `svc-db-openldap` is the directory of record for users and groups.
2. Keycloak's `LDAP user federation` mirrors users into the realm in read-only mode.
3. OpenTalk authenticates users via OIDC and resolves invitee searches via `https://<keycloak>/admin/realms/<realm>/users?search=…`.

## Backend Choice ⚙️

Upstream OpenTalk supports two `[user_search].backend` values: `keycloak_webapi` and `disabled`. There is no native LDAP backend, so binding OpenTalk directly to OpenLDAP would require a custom backend that is not currently maintained.

## Inspect The Keycloak ↔ LDAP Federation 🩺

```bash
make compose-exec cmd="container exec keycloak /opt/keycloak/bin/kcadm.sh get components -r {{ OIDC.CLIENT.REALM }} --query type=org.keycloak.storage.UserStorageProvider"
```

If users created in OpenLDAP do not appear in OpenTalk, force a Keycloak full sync (component IDs vary per environment):

```bash
make compose-exec cmd="container exec keycloak /opt/keycloak/bin/kcadm.sh create user-storage/<id>/sync?action=triggerFullSync -r {{ OIDC.CLIENT.REALM }}"
```
