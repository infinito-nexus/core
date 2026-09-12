"""Collect the provider config a round's variants dictate.

The topic vocabulary and merge semantics live in
``utils.roles.applications.topics``; this module resolves which role demands
what, and refuses two roles demanding different things for one provider.

Only a config topic counts, and only on an entry naming another role's
service. A role's own entity entry is skipped, which is what keeps the two
existing `services.<own>.users` / `services.<own>.domains` declarations from
being read as overrides.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import CONFIG_TOPICS, apply_topic, provider_of

__all__ = ["CONFIG_TOPICS", "NestedOverrideConflictError", "apply_topic"]


class NestedOverrideConflictError(RuntimeError):
    """Two roles in one round demand different config for one provider."""


def _claims(payloads: Mapping[str, Any]) -> list[tuple[str, str, str, Any]]:
    """Return the ``(role, service_key, topic, value)`` a round's payloads carry.

    Args:
        payloads: ``{role: variant payload}`` for one round.

    Reading this before the service registry keeps a round whose variants
    override nothing from paying for the registry at all.
    """
    claims: list[tuple[str, str, str, Any]] = []
    for role_name, payload in payloads.items():
        if not isinstance(payload, Mapping):
            continue
        services = payload.get("services")
        if not isinstance(services, Mapping):
            continue
        for service_key, entry in services.items():
            if not isinstance(entry, Mapping):
                continue
            claims.extend(
                (role_name, service_key, topic, entry[topic])
                for topic in sorted(CONFIG_TOPICS & set(entry))
            )
    return claims


def collect_provider_overrides(
    payloads: Mapping[str, Any], *, roles_dir: str
) -> dict[str, dict[str, Any]]:
    """Return ``{provider: {topic: value}}`` demanded by the round's payloads.

    Args:
        payloads: ``{role: variant payload}`` for one round.
        roles_dir: roles directory the service registry is built from.

    Raises:
        NestedOverrideConflictError: two roles demand different values for the
            same topic of the same provider.
    """
    claims = _claims(payloads)
    if not claims:
        return {}

    registry = build_service_registry_from_roles_dir(Path(roles_dir))
    demanded: dict[str, dict[str, Any]] = {}
    claimed_by: dict[tuple[str, str], str] = {}
    for role_name, service_key, topic, value in claims:
        provider = provider_of(service_key, registry)
        if not provider or provider == role_name:
            continue
        previous = claimed_by.get((provider, topic))
        if previous and demanded[provider][topic] != value:
            raise NestedOverrideConflictError(
                f"{role_name} and {previous} demand different "
                f"{topic!r} for {provider!r} in the same round; a "
                f"round deploys it once, so the two cannot both hold"
            )
        demanded.setdefault(provider, {})[topic] = value
        claimed_by[(provider, topic)] = role_name
    return demanded
