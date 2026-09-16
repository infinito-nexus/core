from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

UDP_ONLY_CATEGORIES = frozenset({"relay", "media", "stun_turn", "stun_turn_tls"})
"""Categories a hidden service cannot carry.

``relay`` and ``media`` are UDP. ``stun_turn`` and its TLS variant do speak TCP,
but the allocation they hand out is a UDP relay address the onion client can
never receive on, so forwarding the signalling port buys nothing.
"""


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
        if category in UDP_ONLY_CATEGORIES:
            continue
        if isinstance(value, int):
            into.add(value)


def collect_onion_ports(
    applications: dict[str, Any],
    deployed_roles: list[str],
) -> list[int]:
    """Single-int TCP ports a deployed role asks for by name under ``ports.onion``.

    ``ports.onion`` is a category-keyed map of booleans alongside ``internal`` /
    ``local`` / ``public``: it names which of a service's already-declared ports
    should answer on the node onion, and nothing else. The port number comes
    from ``ports.local`` when that category is declared there and from
    ``ports.public`` otherwise, which is the precedence ``container_ports``
    publishes by, so the forward always targets the port the service is actually
    reachable on.

    Naming the category is what makes this safe. Sweeping ``ports.public``
    wholesale forwards ports the deployment never publishes -- ldaps 636 is
    declared next to ``network.public: false``, and Mailu's implicit-TLS ports
    are dropped from the publish list whenever TLS is off, which an onion
    deployment always is.
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
            if not isinstance(entity, dict):
                continue
            declared = entity.get("ports")
            if not isinstance(declared, dict):
                continue
            wanted = declared.get("onion")
            if not isinstance(wanted, dict):
                continue
            local = _mapping(declared.get("local"))
            public = _mapping(declared.get("public"))
            for category, flag in wanted.items():
                if category in UDP_ONLY_CATEGORIES or not _as_bool(flag):
                    continue
                value = local.get(category, public.get(category))
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
    '127.0.0.1:<port>'}`` dicts, sorted by port. Two opt-ins are unioned:

      * every port a service names under ``ports.onion`` in meta/services.yml,
        and
      * every port of a service that opts in with ``exposed: true``.

    Both are read from the variant-merged applications view, so a variant that
    drops the opt-in drops the forward with it. The published port binds the
    host interface, so the loopback target reaches it from svc-net-tor's
    host-network container. Composed with the flagged forwards by
    ``lookup('tor_extra_ports')`` and rendered as ``HiddenServicePort`` lines in
    svc-net-tor's torrc.
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

        try:
            applications = lookup_loader.get(
                "applications",
                loader=getattr(self, "_loader", None),
                templar=getattr(self, "_templar", None),
            ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]
        except Exception:  # noqa: BLE001  no merged view -> no ports to forward
            applications = {}
        ports = set(collect_onion_ports(applications, deployed))
        ports.update(collect_exposed_ports(applications, deployed))

        return [
            [
                {"onion_port": port, "target": f"127.0.0.1:{port}"}
                for port in sorted(ports)
            ]
        ]
