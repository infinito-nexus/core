"""Lookup ``role_subnet_exceptions``: the roles whose local subnet sits outside
``NETWORK_ROLE_SUBNET_POOL``.

Usage:

    {{ lookup('role_subnet_exceptions') }}   # ['web-app-bigbluebutton', ...]

A role declares the exception itself, next to the subnet it concerns, with
``local.outside_pool: true`` in its ``meta/networks.yml``. Consumers resolve
the returned ids to subnets through ``lookup('role_subnets', ...)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get as get_app_conf

if TYPE_CHECKING:
    from collections.abc import Mapping

FLAG_PATH = "networks.local.outside_pool"


def outside_pool_roles(applications: Mapping[str, Any]) -> list[str]:
    """Return the sorted ids of the applications that declare the flag.

    Args:
        applications: the merged ``lookup('applications')`` mapping.

    Returns:
        Every application id whose ``networks.local.outside_pool`` is true.
    """
    roles: list[str] = []
    for app_id in sorted(applications):
        flag = get_app_conf(
            applications=applications,
            application_id=app_id,
            config_path=FLAG_PATH,
            strict=False,
            default=False,
            skip_missing_app=True,
        )
        if not isinstance(flag, bool):
            raise AnsibleError(
                f"role_subnet_exceptions: {app_id} {FLAG_PATH} must be a boolean, "
                f"got {flag!r}"
            )
        if flag:
            roles.append(app_id)
    return roles


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if terms:
            raise AnsibleError("lookup('role_subnet_exceptions') expects no terms.")
        applications = lookup_loader.get(
            "applications",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables)[0]
        return [outside_pool_roles(applications)]
