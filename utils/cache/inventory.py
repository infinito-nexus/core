"""Apply a host's inventory to the cache declarations the roles make.

The dev compose stack has no inventory and caches exactly what the roles
declare. A deployed host caches what its configuration says, which starts
from the same declarations and lets the inventory correct or extend them::

    applications:
      svc-cache-package:
        repos:
          raw-example:
            upstream: https://mirror.example.net/
        upstreams:
          example.org:
            read_timeout: 1800s

Both sections are merged per entry, so an inventory that names one field
keeps the rest of the declaration, and a key nobody declared is added.
"""

from __future__ import annotations

from typing import Any

ROLE = "svc-cache-package"


def configured(loader: Any, templar: Any, variables: Any, section: str) -> dict:
    """Return the inventory's entries for one ``cache:`` section.

    Args:
        loader: the lookup plugin's loader.
        templar: the lookup plugin's templar, where it has one.
        variables: the task variables the lookup was called with.
        section: ``repos`` or ``upstreams``.

    Returns:
        The configured entries, or an empty mapping where no inventory
        answers, as in the dev stack.
    """
    from ansible.errors import AnsibleError
    from ansible.plugins.loader import lookup_loader

    try:
        applications = lookup_loader.get(
            "applications", loader=loader, templar=templar
        ).run([], variables=variables or {})[0]
    except (AnsibleError, KeyError, TypeError):
        return {}
    role = applications.get(ROLE) if isinstance(applications, dict) else None
    found = (role or {}).get(section) if isinstance(role, dict) else None
    return found if isinstance(found, dict) else {}


def merge(declared: dict[str, dict], overrides: dict) -> dict[str, dict]:
    """Return *declared* with *overrides* applied, sorted by key.

    Args:
        declared: the entries the roles declare, keyed by name.
        overrides: the inventory's entries for the same section.
    """
    merged = {key: dict(value) for key, value in declared.items()}
    for key, entry in (overrides or {}).items():
        if isinstance(entry, dict):
            merged.setdefault(str(key), {}).update(entry)
    return {key: merged[key] for key in sorted(merged)}
