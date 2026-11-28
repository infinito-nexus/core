"""Per-application RBAC naming for Keycloak: the `ldap-roles-<application_id>` component name of a deployed application's `group-ldap-mapper`."""

from __future__ import annotations

from utils.roles.validation.invokable import list_invokable_app_ids


def kc_per_app_mapper_name(application_id):
    """Return the canonical Keycloak component name for a deployed app's
    per-application `group-ldap-mapper`."""
    if not isinstance(application_id, str) or not application_id:
        raise ValueError(
            "kc_per_app_mapper_name: application_id must be a non-empty string"
        )
    return f"ldap-roles-{application_id}"


def rbac_app_ids(app_ids):
    if app_ids is None:
        app_ids = []
    if not isinstance(app_ids, (list, tuple)):
        raise TypeError(
            f"rbac_app_ids: app_ids must be a list/tuple, got {type(app_ids)}"
        )

    invokable = set(list_invokable_app_ids())
    return sorted({x for x in app_ids if isinstance(x, str) and x in invokable})


class FilterModule:
    def filters(self):
        return {
            "kc_per_app_mapper_name": kc_per_app_mapper_name,
            "rbac_app_ids": rbac_app_ids,
        }
