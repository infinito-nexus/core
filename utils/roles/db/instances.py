"""Instance model for central database engines in database HA on Swarm.

Every host listed in an engine's inventory group holds exactly one instance,
named after and pinned to that host. One host (or any non-swarm mode) renders
today's standalone shape unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.roles.entity.name import get_entity_name
from utils.roles.meta_lookup import (
    get_role_ha,
    get_role_service_keys,
    iter_roles_with_ha,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SWARM_NODE_GROUP = "svc-swarm-node"
FORM_STANDALONE = "standalone"
FORM_HA = "ha"
PRIMARY_PROBE_PREFIX = "primary-probe-"
PRIMARY_PROBE_HTTP = "http"


class DbInstancesError(ValueError):
    pass


def is_valid_quorum_size(count: int) -> bool:
    """Return True for 0, 1 or an odd count of at least 3.

    Args:
        count: number of members in a Raft- or etcd-style quorum group.
    """
    return count <= 1 or (count >= 3 and count % 2 == 1)


def ha_engines() -> frozenset[str]:
    """Return every role whose ``meta/services.yml`` primary entity declares
    ``ha.capable: true``."""
    return frozenset(iter_roles_with_ha())


def data_engines() -> frozenset[str]:
    """Return the HA-capable engines that hold data, i.e. all but the
    coordination store."""
    return frozenset(r for r in ha_engines() if not ha_spec(r)["coordination_store"])


def coordinated_engines() -> frozenset[str]:
    """Return the data engines that declare the coordination store's
    service in their ``meta/services.yml``, i.e. the ones that use it."""
    store = get_entity_name(coordination_store())
    return frozenset(r for r in data_engines() if store in get_role_service_keys(r))


def coordination_store() -> str:
    """Return the one HA-capable role that declares ``ha.coordination_store``."""
    stores = sorted(r for r in ha_engines() if ha_spec(r)["coordination_store"])
    if len(stores) != 1:
        raise DbInstancesError(
            "db_instances: exactly one role must declare ha.coordination_store, "
            f"found {stores}"
        )
    return stores[0]


def ha_spec(application_id: str) -> dict:
    """Return the normalised ``ha`` block of one role.

    Args:
        application_id: any role; one without an ``ha`` block is not capable.

    Returns:
        ``{"capable", "coordination_store", "host_group", "probe",
        "primary_probe", "backup", "sidecar", "endpoint"}`` where ``probe`` is
        the installed binary name of ``primary_probe`` (None without one),
        ``primary_probe`` is a script path or ``"http"`` for the shared
        probe of the ``ha.endpoint`` check, and ``backup`` is ``"sql"``,
        ``"files"`` or None.
    """
    raw = get_role_ha(application_id)
    capable = raw.get("capable") is True
    source = raw.get("primary_probe") if capable else None
    return {
        "capable": capable,
        "coordination_store": capable and raw.get("coordination_store") is True,
        "host_group": raw.get("host_group") if capable else None,
        "probe": (
            f"{PRIMARY_PROBE_PREFIX}{get_entity_name(application_id)}"
            if source
            else None
        ),
        "primary_probe": source,
        "backup": raw.get("backup") if capable else None,
        "sidecar": raw.get("sidecar") if capable else None,
        "endpoint": raw.get("endpoint") if capable else None,
    }


def primary_probes() -> list[dict]:
    """Return the primary probe every HA engine installs.

    Returns:
        ``{"name", "src", "application_id", "entity", "check_port",
        "check_path"}`` per engine. ``name`` is the binary installed next to
        ``resolve-db-primary``. A script probe carries its repository path
        in ``src`` and None in the check fields; an ``http`` probe carries
        None in ``src`` and the ``ha.endpoint`` check port key and path,
        which the installed wrapper hands to the shared HTTP probe.
    """
    probes = []
    for app_id in sorted(ha_engines()):
        spec = ha_spec(app_id)
        if not spec["probe"]:
            continue
        http = spec["primary_probe"] == PRIMARY_PROBE_HTTP
        endpoint = spec["endpoint"] or {}
        probes.append(
            {
                "name": spec["probe"],
                "src": None if http else spec["primary_probe"],
                "application_id": app_id,
                "entity": get_entity_name(app_id),
                "check_port": endpoint.get("check_port") if http else None,
                "check_path": endpoint.get("check_path") if http else None,
            }
        )
    return probes


def engine_word(application_id: str) -> str:
    if application_id not in ha_engines():
        raise DbInstancesError(
            f"db_instances: '{application_id}' is not an HA-capable engine role "
            "(its meta/services.yml primary entity declares no ha.capable)"
        )
    return get_entity_name(application_id)


def sanitize_host_id(hostname: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", hostname.lower()).strip("-")


def instance_volume_name(name: str, instance: dict | None) -> str:
    """Return the docker volume name one instance uses for a role volume.

    Args:
        name: the volume name declared in ``meta/volumes.yml``.
        instance: an entry of ``build_instances()["instances"]``, or None.
    """
    if not instance or instance.get("legacy") or not instance.get("host_id"):
        return name
    return f"{name}_{instance['host_id']}"


def build_instances(
    application_id: str,
    hosts: Sequence[str],
    *,
    deployment_mode: str,
    swarm_nodes: Iterable[str] = (),
    legacy_volume_host: str | None = None,
) -> dict:
    """Return the instance list of one engine.

    Args:
        application_id: engine role, e.g. ``svc-db-postgres``.
        hosts: inventory hosts of the engine group, in inventory order.
        deployment_mode: ``DEPLOYMENT_MODE``; only ``swarm`` can render HA.
        swarm_nodes: hosts in ``svc-swarm-node``; every HA host must be one.
        legacy_volume_host: host already holding ``<engine>_data``; it keeps
            that volume instead of ``<engine>_data_<host-id>``. Defaults to
            the first host, the original standalone host on a migration.

    Returns:
        ``{"form": "standalone"|"ha", "instances": [...], "warnings": [...],
        "ha": ha_spec(application_id)}`` where each instance has ``host``,
        ``host_id``, ``service``, ``volume``.
    """
    engine = get_entity_name(application_id)
    legacy_volume = f"{engine}_data"
    hosts = list(hosts)
    spec = ha_spec(application_id)

    if deployment_mode != "swarm" or len(hosts) <= 1 or not spec["capable"]:
        return {
            "form": FORM_STANDALONE,
            "instances": [
                {
                    "host": hosts[0] if hosts else None,
                    "host_id": None,
                    "service": engine,
                    "volume": legacy_volume,
                    "legacy": True,
                }
            ],
            "warnings": [],
            "ha": spec,
        }

    if legacy_volume_host is None:
        legacy_volume_host = hosts[0]
    eligible = set(swarm_nodes)
    outside = [h for h in hosts if h not in eligible]
    if outside:
        raise DbInstancesError(
            f"db_instances: {application_id} lists hosts not in svc-swarm-node: "
            + ", ".join(outside)
        )

    seen: dict[str, str] = {}
    instances = []
    for host in hosts:
        host_id = sanitize_host_id(host)
        if host_id in seen:
            raise DbInstancesError(
                f"db_instances: hosts '{seen[host_id]}' and '{host}' collide "
                f"on host-id '{host_id}' in {application_id}"
            )
        seen[host_id] = host
        instance = {
            "host": host,
            "host_id": host_id,
            "service": f"{engine}-{host_id}",
            "legacy": host == legacy_volume_host,
        }
        instance["volume"] = instance_volume_name(legacy_volume, instance)
        instances.append(instance)

    warnings = []
    if len(hosts) == 2:
        warnings.append(
            f"{application_id} has 2 instances: there is no drain safety, "
            "losing either host stops writes. List 3 hosts for HA."
        )
    return {"form": FORM_HA, "instances": instances, "warnings": warnings, "ha": spec}


def engine_hosts(application_id: str, groups: Mapping[str, Sequence[str]]) -> list[str]:
    """Return the inventory hosts of one engine.

    Args:
        application_id: engine role, e.g. ``svc-dcs-etcd``.
        groups: Ansible ``groups``; an empty engine group falls back to the
            group the role declares as ``ha.host_group``, if any.
    """
    hosts = list(groups.get(application_id) or [])
    fallback = ha_spec(application_id)["host_group"]
    if hosts or not fallback:
        return hosts
    return list(groups.get(fallback) or [])


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "on", "1"}


def ha_exposure_conflicts(
    application_id: str, app_config: Mapping, *, tor_reachable: bool
) -> list[str]:
    """Return why an engine cannot render its HA form with its current exposure.

    Args:
        application_id: engine role, e.g. ``svc-db-openldap``.
        app_config: the role's merged ``applications`` entry.
        tor_reachable: ``lookup('tor_reachable', application_id)``.

    Returns:
        One message per exposure that proxies to the published local port,
        which the HA form does not publish; empty when the form is safe.
    """
    conflicts = []
    services = (app_config or {}).get("services") or {}
    for key in sorted(services):
        network = (services[key] or {}).get("network") or {}
        if _truthy(network.get("public")):
            conflicts.append(
                f"{application_id}: services.{key}.network.public proxies to the "
                "local port, which the HA form does not publish"
            )
    if tor_reachable:
        conflicts.append(
            f"{application_id}: Tor reachability forwards to the local port, "
            "which the HA form does not publish"
        )
    return conflicts


def departed_instance_services(
    application_id: str,
    stack: str,
    live_services: Iterable[str],
    declared_services: Iterable[str],
) -> list[str]:
    """Return the live per-host services whose host left the engine group.

    Args:
        application_id: engine role, e.g. ``svc-db-redis``.
        stack: swarm stack name of the engine.
        live_services: ``docker stack services`` names, ``<stack>_<service>``.
        declared_services: service keys of the freshly rendered compose file.

    Returns:
        Sorted full service names to remove: live ``<engine>-*`` services
        (instances and their per-host sidecars) the compose file no longer
        declares. The bare ``<engine>`` service is never returned, and a role
        that is not HA-capable has no per-host instances, so none depart.
    """
    if application_id not in ha_engines():
        return []
    declared = set(declared_services)
    if not declared:
        raise DbInstancesError(
            f"db_instances: no declared services for {application_id}; "
            "refusing to compute departed instances from an empty compose file"
        )
    stack_prefix = f"{stack}_"
    instance_prefix = f"{engine_word(application_id)}-"
    departed = []
    for full_name in live_services:
        if not full_name.startswith(stack_prefix):
            continue
        name = full_name[len(stack_prefix) :]
        if name.startswith(instance_prefix) and name not in declared:
            departed.append(full_name)
    return sorted(departed)


def coordination_store_needed(
    groups: Mapping[str, Sequence[str]], deployment_mode: str
) -> bool:
    """Return True when at least one engine that uses the coordination
    store renders its HA form.

    Args:
        groups: Ansible ``groups``.
        deployment_mode: ``DEPLOYMENT_MODE``.
    """
    nodes = list(groups.get(SWARM_NODE_GROUP) or [])
    return any(
        build_instances(
            engine,
            engine_hosts(engine, groups),
            deployment_mode=deployment_mode,
            swarm_nodes=nodes,
        )["form"]
        == FORM_HA
        for engine in sorted(coordinated_engines())
    )
