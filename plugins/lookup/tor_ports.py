from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.base import _resolve_roles_dir
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_UDP_ONLY_CATEGORIES = frozenset({"relay", "media"})


def collect_public_ports(
    deployed_roles: list[str],
    roles_dir: Path,
) -> list[int]:
    """Single-int TCP ``ports.public`` entries of the deployed roles, sorted."""
    ports: set[int] = set()
    for role in deployed_roles:
        services_yml = roles_dir / role / ROLE_FILE_META_SERVICES
        if not services_yml.is_file():
            continue
        data = load_yaml_any(str(services_yml), default_if_missing={})
        if not isinstance(data, dict):
            continue
        for entity in data.values():
            if not isinstance(entity, dict):
                continue
            public = (entity.get("ports") or {}).get("public")
            if not isinstance(public, dict):
                continue
            for category, value in public.items():
                if category in _UDP_ONLY_CATEGORIES:
                    continue
                if isinstance(value, int):
                    ports.add(value)
    return sorted(ports)


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_ports') }}

    Returns the HiddenServicePort mappings for every public TCP port of the
    roles in the current deploy (``group_names``): a list of
    ``{'onion_port': <port>, 'target': '127.0.0.1:<port>'}`` dicts, sorted by
    port. Public ports bind the host interface, so the loopback target reaches
    them. Consumed by ``TOR_ONION_EXTRA_PORTS`` (group_vars/all/19_tor.yml) and
    rendered as ``HiddenServicePort`` lines in svc-net-tor's torrc.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("lookup('tor_ports') expects no terms.")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = variables.get("group_names") or []
        if not isinstance(group_names, list):
            group_names = []

        roles_dir = _resolve_roles_dir(roles_dir=kwargs.get("roles_dir"))
        ports = collect_public_ports([str(g) for g in group_names], roles_dir)
        return [[{"onion_port": port, "target": f"127.0.0.1:{port}"} for port in ports]]
