"""Status predicates over a role's ``meta/variants.yml`` override entries."""

from __future__ import annotations

from typing import Any


def variant_disables_all_services(override: dict[str, Any]) -> bool:
    """True iff a ``meta/variants.yml`` override pins ONLY disabled services.

    Args:
        override: A raw variant entry from
            ``utils.cache.applications.get_variant_overrides_only`` (the
            ``meta/variants.yml`` mapping, NOT the deep-merged config).

    Returns:
        True only when ``override['services']`` is a non-empty mapping and every
        entry sets ``enabled`` to a literal false (Python ``False`` or the
        string ``"false"``). A truthy/Jinja-conditional/absent ``enabled``, a
        non-mapping entry, or an empty/absent ``services`` block all return
        False so the variant stays deployable. Such an all-off variant adds no
        swarm coverage (the all-enabled variant already exercises the role), so
        the swarm test matrix skips it.
    """
    services = override.get("services") if isinstance(override, dict) else None
    if not isinstance(services, dict) or not services:
        return False
    for entry in services.values():
        if not isinstance(entry, dict):
            return False
        enabled = entry.get("enabled")
        disabled = enabled is False or (
            isinstance(enabled, str) and enabled.strip().lower() == "false"
        )
        if not disabled:
            return False
    return True


def deployable_variant_indices(overrides: list[Any] | None) -> list[int]:
    """The variant indices the CI matrix actually deploys for one role.

    Every variant except those whose ``meta/variants.yml`` override disables
    all services (all-off variants add no coverage, since the all-enabled
    variant already exercises the role). This is the single source of truth
    for the per-role job/bundle split: the swarm deploy matrix and the
    ``complexity`` report both count jobs through it.

    Args:
        overrides: The role's raw ``meta/variants.yml`` override list (from
            ``utils.cache.applications.get_variant_overrides_only``), one
            entry per variant.

    Returns:
        The 0-based indices of deployable variants, in order.
    """
    return [
        index
        for index, override in enumerate(overrides or [])
        if not variant_disables_all_services(override)
    ]
