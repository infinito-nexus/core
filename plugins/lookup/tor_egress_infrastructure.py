"""Lookup `tor_egress_infrastructure`: what a Tor node reaches directly by default.

It pre-fills ``services.tor.egress.direct.include`` of ``svc-net-tor``. Every
service named here sees the node's own address; that is the price of updates,
image pulls, time and certificates arriving at clearnet speed and from sources
that refuse Tor exits. The operator edits or empties the list in the inventory.

The entries, in order, all read from ``services.tor.egress.infrastructure``:

- ``mirrors``, the distribution package mirrors;
- ``ntp``, the time servers the distributions default to;
- the registry of every literal image an application in ``group_names`` pulls,
  each followed by the blob hosts ``registry_blob_hosts`` names for it; a port
  is stripped, and loopback, ``localhost`` and address registries are skipped
  because they never leave the node or are no host name;
- ``acme``, the certificate authority endpoints.

The applications payload renders every role's configuration in every role's
context and on every host, so this is a global plugin that reads raw
configuration only and never raises: off a Tor node, or on a malformed block,
it returns an empty list. ``svc-net-tor`` validates the block itself in
``tasks/00_core.yml``. Under ``route: none`` the list is empty too, because a
pre-filled list would fail that validation.

Usage:

    {{ lookup('tor_egress_infrastructure') }}
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name
from utils.networks.tor_egress import ROUTE_NONE

PROVIDER = "svc-net-tor"
DOCKER_HUB = "docker.io"
LOCALHOST = "localhost"


def _registry_host(registry: str) -> str | None:
    """The host name of a registry reference, or None when it is no remote name.

    Args:
        registry: the registry part of an image reference, possibly with a port.
    """
    if registry.startswith("[") and "]" in registry:
        host = registry[1 : registry.index("]")]
    elif registry.count(":") == 1:
        host = registry.rsplit(":", 1)[0]
    else:
        host = registry
    host = host.lower()
    if not host or host == LOCALHOST or host.endswith("." + LOCALHOST):
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    return None


def registries(applications: Mapping[str, Any], group_names: list[str]) -> list[str]:
    """The registry host of every literal image the deployed applications declare.

    Args:
        applications: the merged applications mapping.
        group_names: the application ids deployed on this host.
    """
    found: set[str] = set()
    for application_id in group_names:
        config = applications.get(application_id)
        services = config.get("services") if isinstance(config, Mapping) else None
        if not isinstance(services, Mapping):
            continue
        for service in services.values():
            image = service.get("image") if isinstance(service, Mapping) else None
            if not isinstance(image, str) or "{{" in image:
                continue
            parts = split_registry_and_name(image)
            if parts is None:
                continue
            registry = parts[0]
            if registry is None or registry in DOCKER_HUB_REGISTRIES:
                found.add(DOCKER_HUB)
                continue
            host = _registry_host(registry)
            if host is not None:
                found.add(host)
    return sorted(found)


def infrastructure(
    applications: Mapping[str, Any], group_names: list[str]
) -> list[str]:
    """The pre-filled direct entries, without duplicates.

    Args:
        applications: the merged applications mapping, carrying ``svc-net-tor``.
        group_names: the application ids deployed on this host.
    """
    if PROVIDER not in group_names:
        return []
    try:
        egress = applications[PROVIDER]["services"]["tor"]["egress"]
        declared = egress["infrastructure"]
        route = egress["route"]
        mirrors = list(declared["mirrors"])
        ntp = list(declared["ntp"])
        blob_hosts = dict(declared["registry_blob_hosts"])
        acme = list(declared["acme"])
    except (KeyError, TypeError, ValueError):
        return []
    if str(route).strip() == ROUTE_NONE:
        return []

    entries: list[str] = [*mirrors, *ntp]
    for registry in registries(applications, group_names):
        entries.append(registry)
        if registry in blob_hosts:
            entries.extend(blob_hosts[registry])
    entries.extend(acme)

    seen: dict[str, None] = {}
    for entry in entries:
        seen.setdefault(str(entry), None)
    return list(seen)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("lookup('tor_egress_infrastructure') expects no terms.")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = list(variables.get("group_names") or [])
        if PROVIDER not in group_names:
            return [[]]
        applications = lookup_loader.get(
            "applications",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables)[0]
        return [infrastructure(applications, group_names)]
