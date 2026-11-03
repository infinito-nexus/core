"""Collect the clearnet domains a deploy serves, for the DNS pre-flight."""

from __future__ import annotations

from typing import Any

ONION_SUFFIX = ".onion"


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [domain for entry in value.values() for domain in _flatten(entry)]
    if isinstance(value, (list, tuple, set)):
        return [domain for entry in value for domain in _flatten(entry)]
    return []


def clearnet_domains(domains: Any) -> list[str]:
    """The distinct clearnet domains of a canonical-domains subtree.

    Args:
        domains: one role's ``lookup('domains', role)`` value, a domain, a
            list of them or a mapping onto them, or a list of such values.

    Returns:
        Every domain that is not a ``.onion`` address, lower-cased, without a
        trailing dot, sorted and without duplicates.
    """
    cleaned = {domain.strip().rstrip(".").lower() for domain in _flatten(domains)}
    return sorted(
        domain for domain in cleaned if domain and not domain.endswith(ONION_SUFFIX)
    )
