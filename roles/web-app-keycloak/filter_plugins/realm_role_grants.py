"""Realm roles that mirror an application's RBAC groups.

An application that reads its roles from ``realm_access.roles`` instead of the
groups claim sets ``realm_roles: true`` in ``meta/rbac.yml``. Keycloak then
holds one realm role ``<application_id>-<role>`` per declared role, granted to
the matching ``/<group root>/<application_id>/<role>`` group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

IMPLICIT_ADMIN = "administrator"


def kc_realm_role_grants(
    applications: Mapping[str, Any] | None,
    app_ids: Iterable[str] | None,
    group_root: str,
) -> list[dict[str, str]]:
    """Return one ``{role, group_path}`` grant per role of every opted-in app.

    Args:
        applications: the merged applications mapping.
        app_ids: applications deployed in the current run.
        group_root: the RBAC group root name, ``RBAC.GROUP.NAME``.
    """
    root = "/" + str(group_root).strip("/")
    grants = []
    for app_id in sorted(set(app_ids or [])):
        rbac = ((applications or {}).get(app_id) or {}).get("rbac") or {}
        if rbac.get("realm_roles") is not True:
            continue
        roles = sorted({IMPLICIT_ADMIN, *(rbac.get("roles") or {})})
        grants.extend(
            {"role": f"{app_id}-{role}", "group_path": f"{root}/{app_id}/{role}"}
            for role in roles
        )
    return grants


class FilterModule:
    def filters(self):
        return {"kc_realm_role_grants": kc_realm_role_grants}
