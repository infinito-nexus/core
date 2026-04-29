"""Compute the canonical OIDC group path for an application role.

This lookup is the single sanctioned way to derive the Keycloak group
path that an application role maps to. It replaces the scattered
`[RBAC.GROUP.NAME, ...] | path_join` idiom so that the per-application
OU hierarchy introduced by requirement 005 has one authoritative
producer. See docs/requirements/005-wordpress-multisite-rbac.md.

Usage:
    "{{ lookup('rbac_group_path',
               application_id='web-app-yourls',
               role='administrator') }}"
    -> "roles/web-app-yourls/administrator"

    "{{ lookup('rbac_group_path',
               application_id='web-app-wordpress',
               role='editor',
               tenant='blog.example') }}"
    -> "roles/web-app-wordpress/blog.example/editor"

    "{{ lookup('rbac_group_path',
               application_id='web-app-wordpress',
               role='network-administrator') }}"
    -> "roles/web-app-wordpress/network-administrator"

Contract:
- `application_id` MUST refer to a role that declares an `rbac:` block
  in its `meta/services.yml`. The role may be tenant-aware
  (`rbac.tenancy.axis == "domain"`) or not (default).
- `role` MUST appear under `rbac.roles.<role>` or be the implicit
  `administrator` that requirement 004 auto-adds.
- `tenant` MUST be passed for tenant-aware per-tenant roles, MUST NOT
  be passed for global-scope roles or non-tenant apps.
- Every failure raises AnsibleError with an actionable message.
"""

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

try:
    from ansible.utils.display import Display  # noqa: F401  pragma: no cover
except Exception:  # pragma: no cover
    Display = None  # type: ignore


_IMPLICIT_ADMIN_ROLE = "administrator"
_TENANCY_AXIS_NONE = "none"
_TENANCY_AXIS_DOMAIN = "domain"
_DEFAULT_SCOPE = "per_tenant"
_SCOPE_GLOBAL = "global"


def _get_rbac_group_name(variables):
    """Resolve the top-level group container name (usually "roles")."""
    rbac = variables.get("RBAC") or {}
    group = (rbac.get("GROUP") or {}) if isinstance(rbac, dict) else {}
    name = group.get("NAME") if isinstance(group, dict) else None
    if not isinstance(name, str) or not name:
        raise AnsibleError(
            "rbac_group_path: RBAC.GROUP.NAME is not set in group_vars. "
            "Expected a non-empty string such as 'roles'."
        )
    return name.strip("/")


def _get_application(variables, application_id):
    apps = variables.get("applications")
    if not isinstance(apps, dict):
        raise AnsibleError(
            "rbac_group_path: 'applications' variable is not available. "
            "Make sure the lookup runs after the applications dict has been "
            "merged into host vars."
        )
    app = apps.get(application_id)
    if not isinstance(app, dict):
        raise AnsibleError(
            f"rbac_group_path: application_id '{application_id}' is not "
            f"present in the merged applications dict."
        )
    return app


def _resolve_role_scope(app_cfg, application_id, role):
    """Return the effective scope for a given role.

    For a tenant-aware app the default scope is 'per_tenant'; individual
    roles can override with scope='global'. For a non-tenant app all
    roles are effectively global regardless of their declaration.
    """
    rbac = (app_cfg.get("rbac") or {}) if isinstance(app_cfg, dict) else {}
    if not isinstance(rbac, dict):
        raise AnsibleError(
            f"rbac_group_path: application '{application_id}' has no valid "
            f"'rbac' block in meta/services.yml."
        )

    roles = rbac.get("roles") or {}
    role_cfg = roles.get(role)

    # The implicit `administrator` role from requirement 004 is auto-added
    # for every app with an rbac: block and is always valid.
    if role != _IMPLICIT_ADMIN_ROLE and not isinstance(role_cfg, dict):
        declared = sorted(roles.keys()) if isinstance(roles, dict) else []
        raise AnsibleError(
            f"rbac_group_path: role '{role}' is not declared under "
            f"applications[{application_id}].rbac.roles. Declared roles: "
            f"{declared + [_IMPLICIT_ADMIN_ROLE]}."
        )

    tenancy = (rbac.get("tenancy") or {}) if isinstance(rbac, dict) else {}
    axis = (
        tenancy.get("axis", _TENANCY_AXIS_NONE)
        if isinstance(tenancy, dict)
        else _TENANCY_AXIS_NONE
    )

    if axis == _TENANCY_AXIS_NONE:
        # In non-tenant apps the concept of scope collapses; treat every
        # role as global for the purpose of path construction.
        return _SCOPE_GLOBAL, axis

    if axis != _TENANCY_AXIS_DOMAIN:
        raise AnsibleError(
            f"rbac_group_path: unsupported rbac.tenancy.axis "
            f"'{axis}' on application '{application_id}'. Supported values "
            f"are 'none' (default) and 'domain'."
        )

    # Tenant-aware path: consult per-role scope with default 'per_tenant'.
    scope = _DEFAULT_SCOPE
    if isinstance(role_cfg, dict):
        scope = role_cfg.get("scope", _DEFAULT_SCOPE)
    if scope not in (_DEFAULT_SCOPE, _SCOPE_GLOBAL):
        raise AnsibleError(
            f"rbac_group_path: unsupported scope '{scope}' on "
            f"applications[{application_id}].rbac.roles.{role}. Supported "
            f"values are 'per_tenant' (default) and 'global'."
        )
    return scope, axis


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        variables = variables or {}

        if terms:
            raise AnsibleError(
                "rbac_group_path: positional arguments are not supported. "
                "Use keyword arguments application_id=..., role=..., "
                "tenant=... (optional)."
            )

        application_id = kwargs.get("application_id")
        role = kwargs.get("role")
        tenant = kwargs.get("tenant")

        if not application_id or not isinstance(application_id, str):
            raise AnsibleError(
                "rbac_group_path: 'application_id' is required and must be "
                "a non-empty string."
            )
        if not role or not isinstance(role, str):
            raise AnsibleError(
                "rbac_group_path: 'role' is required and must be a non-empty string."
            )

        app_cfg = _get_application(variables, application_id)
        scope, axis = _resolve_role_scope(app_cfg, application_id, role)
        group_root = _get_rbac_group_name(variables)

        # Requirement 005: hierarchical OIDC claim paths that mirror the
        # LDAP RBAC tree verbatim, with no redundant segments:
        #   /<group_root>/<application_id>/<role_name>                        # non-tenant / global
        #   /<group_root>/<application_id>/<tenant_id>/<role_name>            # per-tenant
        # The Keycloak group tree is materialised by a per-application
        # group-ldap-mapper (see
        # roles/web-app-keycloak/tasks/update/05c_per_app_mappers.yml),
        # anchored at `/<group_root>/<application_id>` with
        # `group.name.ldap.attribute=description`.
        if scope == _SCOPE_GLOBAL:
            if tenant:
                raise AnsibleError(
                    f"rbac_group_path: role '{role}' on application "
                    f"'{application_id}' resolves to scope='global' but a "
                    f"tenant '{tenant}' was passed. Omit the tenant "
                    f"argument for global roles."
                )
            return ["/".join([group_root, application_id, role])]

        if axis != _TENANCY_AXIS_DOMAIN:
            raise AnsibleError(
                f"rbac_group_path: per_tenant scope on "
                f"'{application_id}.{role}' requires "
                f"rbac.tenancy.axis == 'domain' but got '{axis}'."
            )
        if not tenant or not isinstance(tenant, str):
            raise AnsibleError(
                f"rbac_group_path: role '{role}' on application "
                f"'{application_id}' is tenant-scoped; a 'tenant' argument "
                f"is required."
            )
        tenant_norm = tenant.strip().strip("/").lower()
        if not tenant_norm:
            raise AnsibleError(
                "rbac_group_path: 'tenant' argument must be a non-empty "
                "domain after normalisation."
            )
        return ["/".join([group_root, application_id, tenant_norm, role])]
