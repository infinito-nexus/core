"""Compute Keycloak realm RBAC groups + members for the LDAP-disabled path.

Mirrors ``build_ldap_role_entries`` (roles/svc-db-openldap) but emits Keycloak
group paths directly, so the RBAC group tree can be provisioned straight into
the realm when no LDAP federation exists to import it from:

    <group_root>/<application_id>/<role_name>                 # non-tenant / global
    <group_root>/<application_id>/<tenant_id>/<role_name>     # per-tenant

Membership uses the same rule as the LDAP path: a user joins a role group iff
that role name appears in the user's ``roles`` list. Members are restricted to
the users 08_users_realm actually seeds (non-reserved, non-empty password) and
are emitted by their ``username`` attribute (dict key fallback) so the realm
lookup in ensure_group_path_members.sh matches the created accounts. The
implicit ``administrator`` role is auto-added for every RBAC application,
matching the role-list contract.
"""

from ansible.errors import AnsibleFilterError

_IMPLICIT_ADMIN = "administrator"
_AXIS_NONE = "none"
_AXIS_DOMAIN = "domain"
_SCOPE_GLOBAL = "global"
_SCOPE_PER_TENANT = "per_tenant"


def _resolve_tenants(app_cfg, application_id):
    tenancy = (app_cfg.get("rbac") or {}).get("tenancy") or {}
    source = tenancy.get("source", "domains.canonical")
    if source != "domains.canonical":
        raise AnsibleFilterError(
            f"build_realm_rbac_groups: application '{application_id}' declares "
            f"rbac.tenancy.source='{source}', but only 'domains.canonical' is "
            f"implemented."
        )
    canonical = (app_cfg.get("domains") or {}).get("canonical") or []
    tenants = []
    for d in canonical:
        if not isinstance(d, str):
            continue
        norm = d.strip().strip("/").lower()
        if norm and norm not in tenants:
            tenants.append(norm)
    if not tenants:
        raise AnsibleFilterError(
            f"build_realm_rbac_groups: tenant-aware application "
            f"'{application_id}' has no usable domains.canonical entries."
        )
    return tenants


def _members_for_role(users, role_name):
    members = []
    for username, user_config in (users or {}).items():
        cfg = user_config or {}
        if cfg.get("reserved", False):
            continue
        if not cfg.get("password"):
            continue
        user_roles = cfg.get("roles", []) or []
        if role_name in user_roles:
            members.append(cfg.get("username", username))
    return members


def build_realm_rbac_groups(applications, users, group_root, group_names=None):
    """Return ``[{"path": <group_root>/..., "members": [username, ...]}, ...]``."""
    if not isinstance(applications, dict):
        raise AnsibleFilterError(
            "build_realm_rbac_groups: 'applications' must be a dict."
        )
    if not isinstance(group_root, str) or not group_root.strip("/"):
        raise AnsibleFilterError(
            "build_realm_rbac_groups: 'group_root' must be a non-empty string."
        )
    root = group_root.strip("/")

    if group_names is not None:
        deployed = {
            app_id: cfg for app_id, cfg in applications.items() if app_id in group_names
        }
    else:
        deployed = applications

    groups = []
    for application_id, app_cfg in deployed.items():
        if not isinstance(app_cfg, dict):
            continue
        rbac = app_cfg.get("rbac") or {}
        if not isinstance(rbac, dict):
            continue

        roles = {
            **(rbac.get("roles") or {}),
            _IMPLICIT_ADMIN: {"description": _IMPLICIT_ADMIN},
        }

        axis = (rbac.get("tenancy") or {}).get("axis", _AXIS_NONE)
        if axis not in (_AXIS_NONE, _AXIS_DOMAIN):
            raise AnsibleFilterError(
                f"build_realm_rbac_groups: unsupported rbac.tenancy.axis "
                f"'{axis}' on application '{application_id}'."
            )
        tenants = (
            _resolve_tenants(app_cfg, application_id) if axis == _AXIS_DOMAIN else []
        )

        for role_name, role_conf in roles.items():
            declared_scope = (role_conf or {}).get("scope", _SCOPE_PER_TENANT)
            effective_scope = _SCOPE_GLOBAL if axis == _AXIS_NONE else declared_scope
            if effective_scope not in (_SCOPE_GLOBAL, _SCOPE_PER_TENANT):
                raise AnsibleFilterError(
                    f"build_realm_rbac_groups: unsupported scope "
                    f"'{effective_scope}' on "
                    f"applications[{application_id}].rbac.roles.{role_name}."
                )

            members = _members_for_role(users, role_name)

            if effective_scope == _SCOPE_GLOBAL:
                groups.append(
                    {"path": f"{root}/{application_id}/{role_name}", "members": members}
                )
            else:
                groups.extend(
                    {
                        "path": f"{root}/{application_id}/{tenant}/{role_name}",
                        "members": members,
                    }
                    for tenant in tenants
                )

    return groups


class FilterModule:
    def filters(self):
        return {"build_realm_rbac_groups": build_realm_rbac_groups}
