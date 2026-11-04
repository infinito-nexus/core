from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.rbac.catalogue import access_catalogue, approver_grants
from utils.roles.validation.invokable import list_invokable_app_ids


def rbac_requestable_app_ids(group_names):
    """Return the deployed applications whose role groups a user can request.

    Args:
        group_names: the deployment's inventory groups.
    """
    invokable = set(list_invokable_app_ids())
    return sorted({name for name in group_names or [] if name in invokable})


def rbac_access_catalogue(applications, application_ids, group_root):
    """Return the requestable roles of every listed RBAC application.

    Args:
        applications: ``lookup('applications')``.
        application_ids: the deployed applications that declare RBAC.
        group_root: ``RBAC.GROUP.NAME``.
    """
    try:
        return access_catalogue(applications, list(application_ids), group_root)
    except ValueError as error:
        raise AnsibleFilterError(f"rbac_access_catalogue: {error}") from error


def rbac_approver_grants(catalogue, platform_group):
    """Return the role groups each approver group may grant.

    Args:
        catalogue: what ``rbac_access_catalogue`` returns.
        platform_group: path of the platform administrators' group.
    """
    return approver_grants(catalogue, platform_group)


class FilterModule:
    def filters(self):
        return {
            "rbac_access_catalogue": rbac_access_catalogue,
            "rbac_approver_grants": rbac_approver_grants,
            "rbac_requestable_app_ids": rbac_requestable_app_ids,
        }
