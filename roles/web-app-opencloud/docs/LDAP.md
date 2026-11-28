# LDAP Integration 📒

OpenCloud uses the central `svc-db-openldap` instance for user and group lookups. Configuration is rendered into the role's environment file at deploy time using the `LDAP` group_var dictionary, so no LDAP value is hard-coded in the role.

## Variable Mapping 🗺️

| OpenCloud env | Group variable |
|---|---|
| `OC_LDAP_URI` | `LDAP.SERVER.URI` |
| `OC_LDAP_BIND_DN` | `LDAP.DN.ADMINISTRATOR.DATA` |
| `OC_LDAP_BIND_PASSWORD` | `LDAP.BIND_CREDENTIAL` (Vault) |
| `OC_LDAP_USER_BASE_DN` | `LDAP.DN.OU.USERS` |
| `OC_LDAP_GROUP_BASE_DN` | `LDAP.DN.OU.GROUPS` |
| `OC_LDAP_USER_SCHEMA_USERNAME` | `LDAP.USER.ATTRIBUTES.ID` |
| `OC_LDAP_USER_SCHEMA_MAIL` | `LDAP.USER.ATTRIBUTES.MAIL` |
| `OC_LDAP_USER_SCHEMA_DISPLAY_NAME` | `LDAP.USER.ATTRIBUTES.FULLNAME` |

## Read-only Mode 🔒

`GRAPH_LDAP_SERVER_WRITE_ENABLED=false` keeps OpenCloud from modifying the directory. User lifecycle is owned by the LDAP and Keycloak side.

## Account Flag 🚩

The directory schema has no `openCloudUserEnabled` attribute type. The built-in identity provider ANDs `(!(openCloudUserEnabled=FALSE))` into its user search by default, OpenLDAP evaluates a filter on an unknown attribute type as Undefined, and the search then matches no account, so every built-in sign-in fails with "Logon failed". `IDP_USER_ENABLED_ATTRIBUTE=` empties the flag for the identity provider only, in line with `OC_LDAP_DISABLE_USER_MECHANISM=none`; Graph and the users service keep their settings.

## Inspect LDAP Entries 🩺

```bash
make compose-exec cmd="container exec opencloud opencloud users list"
```
