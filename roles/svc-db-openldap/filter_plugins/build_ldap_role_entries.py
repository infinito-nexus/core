"""Build structured LDAP role entries for the RBAC groups container.

Requirement 005 mandates a hierarchical Keycloak group path shape:

    /roles/<application_id>/<role_name>                    # non-tenant / global
    /roles/<application_id>/<tenant_id>/<role_name>        # per-tenant

Keycloak's `group-ldap-mapper` with `preserve.group.inheritance=true`
reconstructs group hierarchy **only from `member` references between
groups that all live at the same search-base level**, not from LDAP DN
nesting. Groups nested via DN (`cn=role,cn=app,ou=roles,...`) are
silently dropped during sync. This filter therefore:

* Emits every group entry as a direct child of the roles OU (flat DN),
  with a disambiguated `cn` value:
    cn=<application_id>                                        # app container
    cn=<application_id>-<role_name>                            # non-tenant / global role
    cn=<application_id>-<tenant_id>                            # tenant container
    cn=<application_id>-<tenant_id>-<role_name>                # per-tenant role
* Populates each entry's `description` with the final path segment
  (`<application_id>`, `<tenant_id>`, or `<role_name>`). The Keycloak
  mapper's `group.name.ldap.attribute=description` uses this as the
  visible Keycloak group name, so the resulting group paths are
  `/roles/<application_id>/<role_name>` and
  `/roles/<application_id>/<tenant_id>/<role_name>` as required.
* Connects parents to children via `member` references. Keycloak turns
  each referenced child groupOfNames into a Keycloak subgroup of the
  referring parent, building the required hierarchy.

See:
    docs/requirements/004-generic-rbac-ldap-auto-provisioning.md
    docs/requirements/005-wordpress-multisite-rbac.md
"""

_ENTRY_KIND_GROUP = "group"
_TENANCY_AXIS_NONE = "none"
_TENANCY_AXIS_DOMAIN = "domain"
_SCOPE_GLOBAL = "global"
_SCOPE_PER_TENANT = "per_tenant"
_IMPLICIT_ADMIN = "administrator"
_IMPLICIT_ADMIN_DESC = "administrator"


def _resolve_tenants(application_config, application_id):
    """Return the list of tenant identifiers for a tenant-aware app."""
    tenancy = (application_config.get("rbac") or {}).get("tenancy") or {}
    source = tenancy.get("source", "server.domains.canonical")
    if source != "server.domains.canonical":
        raise ValueError(
            f"build_ldap_role_entries: application '{application_id}' "
            f"declares rbac.tenancy.source='{source}', but only "
            f"'server.domains.canonical' is implemented."
        )
    server = application_config.get("server") or {}
    domains = server.get("domains") or {}
    canonical = domains.get("canonical") or []
    if not canonical:
        raise ValueError(
            f"build_ldap_role_entries: tenant-aware application "
            f"'{application_id}' has no server.domains.canonical entries."
        )
    tenants = []
    for d in canonical:
        if not isinstance(d, str):
            continue
        norm = d.strip().strip("/").lower()
        if norm and norm not in tenants:
            tenants.append(norm)
    if not tenants:
        raise ValueError(
            f"build_ldap_role_entries: application '{application_id}' has "
            f"an empty canonical domain list after normalisation."
        )
    return tenants


def _container_entry(cn, dn, display_name, child_dns, placeholder_dn):
    """Intermediate groupOfNames container; members are child-group DNs."""
    members = list(child_dns) if child_dns else []
    if not members:
        if not placeholder_dn:
            raise ValueError(
                "LDAP.RBAC.EMPTY_MEMBER_DN must be defined when using groupOfNames"
            )
        members = [placeholder_dn]
    return {
        "kind": _ENTRY_KIND_GROUP,
        "dn": dn,
        "cn": cn,
        "description": display_name,
        "objectClass": ["top", "groupOfNames"],
        "member": members,
    }


def _role_group_entry(
    cn,
    dn,
    display_name,
    flavors,
    group_id,
    member_uids,
    member_dns,
    placeholder_dn,
):
    entry = {
        "kind": _ENTRY_KIND_GROUP,
        "dn": dn,
        "cn": cn,
        "description": display_name,
        "objectClass": ["top"] + list(flavors),
    }
    if "posixGroup" in flavors:
        entry["gidNumber"] = group_id
        if member_uids:
            entry["memberUid"] = member_uids
    if "groupOfNames" in flavors:
        if member_dns:
            entry["member"] = member_dns
        else:
            if not placeholder_dn:
                raise ValueError(
                    "LDAP.RBAC.EMPTY_MEMBER_DN must be defined when using groupOfNames"
                )
            entry["member"] = [placeholder_dn]
    return entry


def build_ldap_role_entries(applications, users, ldap, group_names=None):
    """Return ``{dn: entry}`` for every container and role group the RBAC tree needs."""

    result = {}
    placeholder_dn = ldap.get("RBAC", {}).get("EMPTY_MEMBER_DN")

    if group_names is not None:
        deployed_apps = {
            app_id: cfg for app_id, cfg in applications.items() if app_id in group_names
        }
    else:
        deployed_apps = applications

    role_dn_base = ldap["DN"]["OU"]["ROLES"]
    user_dn_base = ldap["DN"]["OU"]["USERS"]
    ldap_user_attr = ldap["USER"]["ATTRIBUTES"]["ID"]
    flavors = ldap.get("RBAC", {}).get("FLAVORS") or []

    for application_id, application_config in deployed_apps.items():
        rbac = application_config.get("rbac") or {}
        if not isinstance(rbac, dict):
            continue

        base_roles = rbac.get("roles") or {}
        roles = {
            **base_roles,
            _IMPLICIT_ADMIN: {"description": _IMPLICIT_ADMIN_DESC},
        }

        tenancy = rbac.get("tenancy") or {}
        axis = tenancy.get("axis", _TENANCY_AXIS_NONE)
        if axis not in (_TENANCY_AXIS_NONE, _TENANCY_AXIS_DOMAIN):
            raise ValueError(
                f"build_ldap_role_entries: unsupported rbac.tenancy.axis "
                f"'{axis}' on application '{application_id}'."
            )

        group_id = application_config.get("group_id")

        tenants = []
        if axis == _TENANCY_AXIS_DOMAIN:
            tenants = _resolve_tenants(application_config, application_id)

        app_container_cn = application_id
        app_container_dn = f"cn={app_container_cn},{role_dn_base}"

        role_groups_to_emit = []
        tenant_containers_to_emit = []
        app_child_dns = []

        for role_name, role_conf in roles.items():
            declared_scope = (role_conf or {}).get("scope", _SCOPE_PER_TENANT)
            effective_scope = (
                _SCOPE_GLOBAL if axis == _TENANCY_AXIS_NONE else declared_scope
            )
            if effective_scope not in (_SCOPE_PER_TENANT, _SCOPE_GLOBAL):
                raise ValueError(
                    f"build_ldap_role_entries: unsupported scope "
                    f"'{effective_scope}' on "
                    f"applications[{application_id}].rbac.roles.{role_name}."
                )

            member_dns = []
            member_uids = []
            for username, user_config in (users or {}).items():
                user_roles = (user_config or {}).get("roles", []) or []
                if role_name in user_roles:
                    user_dn = f"{ldap_user_attr}={username},{user_dn_base}"
                    member_dns.append(user_dn)
                    member_uids.append(username)

            if effective_scope == _SCOPE_GLOBAL:
                role_cn = f"{application_id}-{role_name}"
                role_dn = f"cn={role_cn},{role_dn_base}"
                role_groups_to_emit.append(
                    (role_cn, role_dn, role_name, member_uids, member_dns)
                )
                app_child_dns.append(role_dn)
            else:
                for tenant in tenants:
                    role_cn = f"{application_id}-{tenant}-{role_name}"
                    role_dn = f"cn={role_cn},{role_dn_base}"
                    role_groups_to_emit.append(
                        (role_cn, role_dn, role_name, member_uids, member_dns)
                    )

        # Tenant containers reference per-tenant role groups.
        for tenant in tenants:
            tenant_cn = f"{application_id}-{tenant}"
            tenant_dn = f"cn={tenant_cn},{role_dn_base}"
            tenant_member_dns = [
                dn
                for _cn, dn, _rn, _uids, _dns in role_groups_to_emit
                if _cn.startswith(f"{application_id}-{tenant}-")
            ]
            tenant_containers_to_emit.append(
                (tenant_cn, tenant_dn, tenant, tenant_member_dns)
            )
            app_child_dns.append(tenant_dn)

        # Emit parent-first: app container → tenant containers → role groups.
        result[app_container_dn] = _container_entry(
            cn=app_container_cn,
            dn=app_container_dn,
            display_name=application_id,
            child_dns=app_child_dns,
            placeholder_dn=placeholder_dn,
        )
        for (
            tenant_cn,
            tenant_dn,
            tenant_display,
            tenant_member_dns,
        ) in tenant_containers_to_emit:
            result[tenant_dn] = _container_entry(
                cn=tenant_cn,
                dn=tenant_dn,
                display_name=tenant_display,
                child_dns=tenant_member_dns,
                placeholder_dn=placeholder_dn,
            )
        for (
            role_cn,
            role_dn,
            display_name,
            member_uids,
            member_dns,
        ) in role_groups_to_emit:
            result[role_dn] = _role_group_entry(
                cn=role_cn,
                dn=role_dn,
                display_name=display_name,
                flavors=flavors,
                group_id=group_id,
                member_uids=member_uids,
                member_dns=member_dns,
                placeholder_dn=placeholder_dn,
            )

    return result


class FilterModule(object):
    def filters(self):
        return {"build_ldap_role_entries": build_ldap_role_entries}
