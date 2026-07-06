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


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _collect_local_tcp_ports(port_categories: Any, into: set[int]) -> None:
    """Add single-int TCP ports of the loopback-published ``ports.local`` group
    only. An exposed service publishes just its local plaintext port to
    127.0.0.1, so the onion HiddenServicePort must target that; forwarding a
    ``public`` TLS port (e.g. ldaps 636) would be a dead loopback target (nothing
    listens there in the exposed variant) and plaintext-into-TLS."""
    if not isinstance(port_categories, dict):
        return
    local = port_categories.get("local")
    if not isinstance(local, dict):
        return
    for category, value in local.items():
        if category in _UDP_ONLY_CATEGORIES:
            continue
        if isinstance(value, int):
            into.add(value)


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
        tor = data.get("tor")
        if not (isinstance(tor, dict) and _as_bool(tor.get("enabled"))):
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


def collect_exposed_ports(
    applications: dict[str, Any],
    deployed_roles: list[str],
) -> list[int]:
    """Single-int TCP ports of every deployed service flagged ``exposed: true``
    in the variant-merged ``applications`` view, sorted.

    ``exposed`` is an explicit per-service opt-in (default false) that makes the
    service reachable over the node onion: its port gets a dedicated
    ``HiddenServicePort``. Because ``applications`` is the variant-merged config
    (base ``meta/services.yml`` deep-merged with the round's ``meta/variants.yml``
    override), a service is forwarded only in the variant/config where it sets
    ``exposed: true`` — which is exactly what lets the two DB variants be tested
    over Tor (v0 exposed -> reachable, v1 not -> refused).
    """
    ports: set[int] = set()
    deployed = set(deployed_roles)
    if not isinstance(applications, dict):
        return []
    for app_id, cfg in applications.items():
        if app_id not in deployed:
            continue
        services = (cfg or {}).get("services") if isinstance(cfg, dict) else None
        if not isinstance(services, dict):
            continue
        for entity in services.values():
            if not isinstance(entity, dict) or not _as_bool(entity.get("exposed")):
                continue
            _collect_local_tcp_ports(entity.get("ports"), ports)
    return sorted(ports)


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_ports') }}

    Returns the HiddenServicePort mappings for the roles in the current deploy
    (``group_names``): a list of ``{'onion_port': <port>, 'target':
    '127.0.0.1:<port>'}`` dicts, sorted by port. Two sources are unioned:

      * every ``ports.public`` TCP port of tor-enabled roles, and
      * every port of a service that opts in with ``exposed: true`` (resolved
        against the variant-merged applications view, so per-variant).

    Public/exposed ports bind the host interface, so the loopback target reaches
    them from svc-net-tor's host-network container. Consumed by
    ``TOR_ONION_EXTRA_PORTS`` (group_vars/all/19_tor.yml) and rendered as
    ``HiddenServicePort`` lines in svc-net-tor's torrc.
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
        deployed = [str(g) for g in group_names]

        roles_dir = _resolve_roles_dir(roles_dir=kwargs.get("roles_dir"))
        ports = set(collect_public_ports(deployed, roles_dir))

        from utils.cache.applications import get_merged_applications

        try:
            applications = get_merged_applications(
                variables=variables,
                roles_dir=kwargs.get("roles_dir"),
                templar=getattr(self, "_templar", None),
            )
        except Exception:  # noqa: BLE001  no merged view -> exposed ports simply unavailable
            applications = {}
        ports.update(collect_exposed_ports(applications, deployed))

        return [
            [
                {"onion_port": port, "target": f"127.0.0.1:{port}"}
                for port in sorted(ports)
            ]
        ]
