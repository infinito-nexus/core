"""Backup view of the database instance model in database HA on Swarm."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from utils.roles.db.instances import (
    FORM_HA,
    SWARM_NODE_GROUP,
    build_instances,
    engine_hosts,
    engine_word,
    ha_engines,
    ha_spec,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

BACKUP_SQL = "sql"
BACKUP_ROLE = "svc-bkp-volume-2-local"


def backed_up_engines() -> list[str]:
    """Return the sorted HA engines that declare ``ha.backup``."""
    return sorted(r for r in ha_engines() if ha_spec(r)["backup"])


def _ha_models(
    groups: Mapping[str, Sequence[str]], deployment_mode: str
) -> list[tuple[str, dict]]:
    nodes = list(groups.get(SWARM_NODE_GROUP) or [])
    models = []
    for app_id in backed_up_engines():
        model = build_instances(
            app_id,
            engine_hosts(app_id, groups),
            deployment_mode=deployment_mode,
            swarm_nodes=nodes,
        )
        if model["form"] == FORM_HA:
            models.append((app_id, model))
    return models


def ha_instance_hosts(
    groups: Mapping[str, Sequence[str]], deployment_mode: str
) -> list[str]:
    """Return every host holding an instance of a backed-up engine in HA form.

    Args:
        groups: Ansible ``groups``.
        deployment_mode: ``DEPLOYMENT_MODE``.
    """
    hosts = {
        instance["host"]
        for _, model in _ha_models(groups, deployment_mode)
        for instance in model["instances"]
    }
    return sorted(hosts)


def local_backup_instances(
    groups: Mapping[str, Sequence[str]],
    deployment_mode: str,
    host: str,
    bin_dir: str,
) -> list[dict]:
    """Return the HA instances pinned to ``host`` that the backup gate probes.

    Args:
        groups: Ansible ``groups``.
        deployment_mode: ``DEPLOYMENT_MODE``.
        host: inventory hostname of the backup unit's host.
        bin_dir: directory the engines' primary probes are installed in.

    Returns:
        One ``{"engine", "service", "volume", "probe", "sql"}`` per local
        instance, where ``service`` is the full swarm service name
        ``<stack>_<instance>``, ``probe`` the argv asking the engine's own
        primary probe about that instance, and ``sql`` says baudolo must
        dump it.
    """
    result = []
    for app_id, model in _ha_models(groups, deployment_mode):
        engine = engine_word(app_id)
        spec = model["ha"]
        for instance in model["instances"]:
            if instance["host"] != host:
                continue
            result.append(
                {
                    "engine": engine,
                    "service": f"{engine}_{instance['service']}",
                    "volume": instance["volume"],
                    "probe": [
                        str(PurePosixPath(bin_dir) / spec["probe"]),
                        engine,
                        instance["service"],
                    ],
                    "sql": spec["backup"] == BACKUP_SQL,
                }
            )
    return result
