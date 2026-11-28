"""Which roles of a request an approver may confirm, as the service shows it.

Keycloak's fine-grained admin permissions decide every grant. This check only
keeps the review page from offering a role Keycloak would refuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Person


def grantable(
    approver: Person,
    catalogue_roles: list[dict[str, Any]],
    requested: list[str],
    platform_group: str,
) -> list[str]:
    """Return the ids of the requested roles the approver may grant.

    Args:
        approver: the signed-in approver.
        catalogue_roles: every catalogue entry of the request's application.
        requested: the role ids the request names.
        platform_group: group path of the platform administrators, who may
            grant every role.
    """
    wanted = [r for r in catalogue_roles if r["id"] in requested]
    if platform_group in approver.groups:
        return [r["id"] for r in wanted]
    administrators = {
        r["path"]
        for r in catalogue_roles
        if r["role"] == "administrator" and not r["tenant"]
    }
    if not administrators.intersection(approver.groups):
        return []
    return [r["id"] for r in wanted if not r["administrator"]]
