"""Read the gathered facts a package plan needs off either fact shape."""

from __future__ import annotations

from typing import Any


def read_fact(facts: dict[str, Any], name: str) -> str:
    """Read a fact from either the task_vars shape or the setup-module one.

    Args:
        facts: an ``ansible_facts`` mapping. task_vars carries bare keys,
            the setup module returns them ``ansible_``-prefixed.
        name: the unprefixed fact name.
    """
    for key in (name, f"ansible_{name}"):
        value = facts.get(key)
        if value:
            return str(value).strip()
    return ""


def distribution_and_family(facts: dict[str, Any]) -> tuple[str, str]:
    """Return ``(distribution, os_family)``, or ``("", "")`` if either is absent."""
    distribution = read_fact(facts, "distribution").lower()
    os_family = read_fact(facts, "os_family")
    if not distribution or not os_family:
        return "", ""
    return distribution, os_family
