"""Lab-shape facts the swarm matrix needs beyond the node names."""

from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.db.instances import data_engines
from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from collections.abc import Mapping


def application_overrides(base: Mapping[str, Any]) -> dict:
    """Return *base* with the ``applications`` subtree of the lab-size override file laid over it.

    The failover suite points ``SWARM_DATA_LAB_VARS`` at that file; unset, the
    drill keeps the production sizes.

    Args:
        base: ``application_id`` -> overrides the round already carries.
    """
    path = os.environ.get("SWARM_DATA_LAB_VARS")
    if not path:
        return dict(base)
    lab_apps = (load_yaml_any(path, default_if_missing={}) or {}).get("applications")
    return {**base, **(lab_apps or {})}


def is_ha_lab() -> bool:
    """Return True when the lab runs the ``ha`` database shape."""
    return (os.environ.get("INFINITO_SWARM_DB_TOPOLOGY") or "").strip() == "ha"


def without_engine_exposure(variant_payloads: Mapping[str, Any]) -> dict[str, Any]:
    """Return *variant_payloads* with every data engine's own port unexposed.

    The HA form publishes no local port, so ``db_ha_prepare`` refuses an
    engine variant that exposes it over the onion; an HA lab therefore deploys
    the engines unexposed. Outside an HA lab the payloads come back unchanged.

    Args:
        variant_payloads: ``application_id`` -> rendered variant config.
    """
    payloads = copy.deepcopy(dict(variant_payloads))
    if not is_ha_lab():
        return payloads
    for app_id in data_engines():
        payload = payloads.get(app_id)
        if not isinstance(payload, dict):
            continue
        service = (payload.get("services") or {}).get(get_entity_name(app_id))
        if isinstance(service, dict) and "exposed" in service:
            service["exposed"] = False
    return payloads
