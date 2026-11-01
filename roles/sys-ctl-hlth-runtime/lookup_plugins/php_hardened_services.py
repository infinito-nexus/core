from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name

HARDENING_VOLUME = "php_hardening"


def hardened_services(volumes: Any) -> list[str]:
    """Return the services that mount the shared PHP hardening ini.

    Args:
        volumes: the role's canonical ``meta/volumes.yml`` mapping.

    Returns:
        The sorted service keys listed under ``php_hardening.mounts``.
    """
    if not isinstance(volumes, Mapping):
        return []
    entry = volumes.get(HARDENING_VOLUME)
    if not isinstance(entry, Mapping):
        return []
    return sorted(
        {
            str(mount["service"])
            for mount in entry.get("mounts") or []
            if isinstance(mount, Mapping) and mount.get("service")
        }
    )


class LookupModule(LookupBase):
    """``lookup('php_hardened_services', group_names=<role ids>)``.

    Args:
        group_names: the deployed role ids.

    Returns:
        ``{entity: [service, ...]}`` for every role whose ``meta/volumes.yml``
        declares ``php_hardening``; the entity is the compose project and
        swarm stack name.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, list[str]]]:
        group_names = kwargs.get("group_names")
        if not isinstance(group_names, (list, tuple)):
            raise AnsibleError(
                "php_hardened_services: group_names must be a list of role ids"
            )

        volume = lookup_loader.get(
            "volume", loader=self._loader, templar=getattr(self, "_templar", None)
        )
        result: dict[str, list[str]] = {}
        for role_id in sorted({str(name) for name in group_names}):
            services = hardened_services(volume.run([role_id], variables=variables)[0])
            if services:
                result[get_entity_name(role_id)] = services
        return [result]
