from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ONION_SUFFIX = "_onion"


def unserved_canonical_keys(services: Any) -> set[str]:
    """Return the canonical domain keys an application does not serve.

    Args:
        services: the application's ``services`` mapping. An entity that lists
            ``domains`` claims those canonical keys.

    Returns:
        The keys of every claiming entity that is disabled, or enabled but
        shared, because its provider serves that surface instead.
    """
    keys: set[str] = set()
    if not isinstance(services, Mapping):
        return keys
    for entity in services.values():
        if not isinstance(entity, Mapping) or "domains" not in entity:
            continue
        if entity.get("enabled") and not entity.get("shared"):
            continue
        claimed = entity.get("domains")
        if isinstance(claimed, str):
            claimed = [claimed]
        if not isinstance(claimed, (list, tuple)):
            continue
        keys.update(str(key) for key in claimed if key)
    return keys


def served_domains(domains: Any, services: Any) -> list[str]:
    """Return the domains of one application that it serves itself.

    Args:
        domains: the application's entry of the resolved domains map, a list,
            or a mapping of canonical key to domain where onion mirrors sit
            under ``<key>_onion``.
        services: the application's ``services`` mapping.

    Returns:
        The domain values without those of the keys
        ``unserved_canonical_keys`` names and without their onion mirrors.
    """
    if not isinstance(domains, Mapping):
        return [str(domain) for domain in (domains or [])]
    skipped = unserved_canonical_keys(services)
    served: list[str] = []
    for key, domain in domains.items():
        name = str(key)
        base = name.removesuffix(ONION_SUFFIX)
        if name in skipped or base in skipped:
            continue
        served.append(str(domain))
    return served
