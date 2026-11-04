"""The requestable roles of every RBAC application, built from its ``meta/rbac.yml``.

The access-request service lists these roles on its form and the Keycloak role
derives the fine-grained admin permissions from the same entries, so who may
request a role and who may grant it never drift apart.
"""

from __future__ import annotations

from typing import Any

IMPLICIT_ADMINISTRATOR = "administrator"
ADMINISTRATOR_SUFFIX = "-" + IMPLICIT_ADMINISTRATOR
REALM_MANAGEMENT_KEY = "realm_management"
_AXIS_NONE = "none"
_AXIS_DOMAIN = "domain"
_SCOPE_GLOBAL = "global"
_SCOPE_PER_TENANT = "per_tenant"


def is_administrator_role(name: str, spec: dict[str, Any] | None = None) -> bool:
    """Return True for a role that administers its application or the realm.

    Args:
        name: role name as declared in ``meta/rbac.yml``.
        spec: its declaration; a non-empty ``realm_management`` list grants
            Keycloak admin rights, so only a platform administrator may grant it.
    """
    if (spec or {}).get(REALM_MANAGEMENT_KEY):
        return True
    return name == IMPLICIT_ADMINISTRATOR or name.endswith(ADMINISTRATOR_SUFFIX)


def _tenants(application_id: str, application: dict[str, Any]) -> list[str]:
    tenants: list[str] = []
    for domain in (application.get("domains") or {}).get("canonical") or []:
        if isinstance(domain, str):
            tenant = domain.strip().strip("/").lower()
            if tenant and tenant not in tenants:
                tenants.append(tenant)
    if not tenants:
        raise ValueError(
            f"tenant-aware application '{application_id}' has no domains.canonical entry"
        )
    return tenants


def application_roles(
    application_id: str, application: dict[str, Any], group_root: str
) -> list[dict[str, Any]]:
    """Return the requestable roles of one application in declaration order.

    Args:
        application_id: the application's role name.
        application: its merged applications payload.
        group_root: ``RBAC.GROUP.NAME``, the root of every role group path.

    Returns:
        One ``{id, role, tenant, description, path, administrator}`` mapping
        per role group: ``id`` is the path below the application, ``path``
        the full Keycloak group path with one leading slash. The implicit
        ``administrator`` is appended when the file does not declare it.

    Raises:
        ValueError: an unknown tenancy axis or scope, or a tenant-aware
            application without canonical domains.
    """
    rbac = application.get("rbac") or {}
    declared = dict(rbac.get("roles") or {})
    declared.setdefault(IMPLICIT_ADMINISTRATOR, {})
    axis = (rbac.get("tenancy") or {}).get("axis", _AXIS_NONE)
    if axis not in (_AXIS_NONE, _AXIS_DOMAIN):
        raise ValueError(f"unknown rbac.tenancy.axis '{axis}' on '{application_id}'")
    tenants = _tenants(application_id, application) if axis == _AXIS_DOMAIN else []
    root = "/" + group_root.strip("/")
    entries = []
    for role, spec in declared.items():
        scope = (
            _SCOPE_GLOBAL
            if axis == _AXIS_NONE
            else (spec or {}).get("scope", _SCOPE_PER_TENANT)
        )
        if scope not in (_SCOPE_GLOBAL, _SCOPE_PER_TENANT):
            raise ValueError(f"unknown scope '{scope}' on '{application_id}.{role}'")
        description = str((spec or {}).get("description") or "").strip()
        for tenant in tenants if scope == _SCOPE_PER_TENANT else [""]:
            below = f"{tenant}/{role}" if tenant else role
            entries.append(
                {
                    "id": below,
                    "role": role,
                    "tenant": tenant,
                    "description": description,
                    "path": f"{root}/{application_id}/{below}",
                    "administrator": is_administrator_role(role, spec),
                }
            )
    return entries


def access_catalogue(
    applications: dict[str, Any], application_ids: list[str], group_root: str
) -> dict[str, dict[str, Any]]:
    """Return the role catalogue of every listed RBAC application.

    Args:
        applications: ``lookup('applications')``.
        application_ids: the deployed applications that declare RBAC.
        group_root: ``RBAC.GROUP.NAME``.

    Returns:
        Application id mapped to ``{roles, default}``: ``roles`` as
        ``application_roles`` returns them, ``default`` the ``id`` of the
        least-privileged role, the first declared role that does not
        administer the application, or None when only administrators exist.
    """
    catalogue = {}
    for application_id in sorted(set(application_ids)):
        application = applications.get(application_id)
        if not isinstance(application, dict):
            continue
        roles = application_roles(application_id, application, group_root)
        default = next((r["id"] for r in roles if not r["administrator"]), None)
        catalogue[application_id] = {"roles": roles, "default": default}
    return catalogue


def delegated_groups(catalogue: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return what each application administrator group may grant.

    Args:
        catalogue: what ``access_catalogue`` returns.

    Returns:
        One ``{application, approver, groups}`` mapping per application with
        at least one grantable role: ``approver`` is the path of the
        application's ``administrator`` group, ``groups`` the paths of its
        roles that do not administer it.
    """
    delegations = []
    for application_id, entry in sorted(catalogue.items()):
        approver = next(
            (
                r["path"]
                for r in entry["roles"]
                if r["role"] == IMPLICIT_ADMINISTRATOR and not r["tenant"]
            ),
            None,
        )
        groups = [r["path"] for r in entry["roles"] if not r["administrator"]]
        if approver and groups:
            delegations.append(
                {"application": application_id, "approver": approver, "groups": groups}
            )
    return delegations


def approver_grants(
    catalogue: dict[str, dict[str, Any]], platform_group: str
) -> list[dict[str, Any]]:
    """Return the role groups each approver group may grant.

    Args:
        catalogue: what ``access_catalogue`` returns.
        platform_group: path of the platform administrators' group.

    Returns:
        One ``{approver, groups}`` mapping per approver group: the platform
        group first with every role group of the catalogue, then each
        application administrator group with what ``delegated_groups`` gives it.
    """
    every = sorted({r["path"] for entry in catalogue.values() for r in entry["roles"]})
    return [
        {"approver": platform_group, "groups": every},
        *(
            {"approver": d["approver"], "groups": d["groups"]}
            for d in delegated_groups(catalogue)
            if d["approver"] != platform_group
        ),
    ]
