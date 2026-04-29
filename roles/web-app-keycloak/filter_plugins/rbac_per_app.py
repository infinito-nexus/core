"""Per-application RBAC naming for Keycloak (requirement 005).

Single SPOT for the strings that vary per deployed application in the
per-app `group-ldap-mapper` setup:

* the Keycloak component name `ldap-roles-<application_id>`
* the LDAP filter that surfaces only that application's role groups

These names are referenced from `vars/main.yml`
(`KEYCLOAK_PER_APP_LDAP_ROLES_MAPPER`) and from the host-side
`upsert_app_mapper.sh` script. Centralising them here means a future
rename of the mapper convention is a one-line change in this plugin
and stays consistent everywhere.
"""


def kc_per_app_mapper_name(application_id):
    """Return the canonical Keycloak component name for a deployed app's
    per-application `group-ldap-mapper`."""
    if not isinstance(application_id, str) or not application_id:
        raise ValueError(
            "kc_per_app_mapper_name: application_id must be a non-empty string"
        )
    return f"ldap-roles-{application_id}"


def kc_per_app_ldap_filter(application_id):
    """Return the LDAP filter that surfaces an application's role groups
    (`cn=<application_id>-...`) without leaking entries that belong to
    other applications."""
    if not isinstance(application_id, str) or not application_id:
        raise ValueError(
            "kc_per_app_ldap_filter: application_id must be a non-empty string"
        )
    return f"(&(objectClass=groupOfNames)(cn={application_id}-*))"


class FilterModule(object):
    def filters(self):
        return {
            "kc_per_app_mapper_name": kc_per_app_mapper_name,
            "kc_per_app_ldap_filter": kc_per_app_ldap_filter,
        }
