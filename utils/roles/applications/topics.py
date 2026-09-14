"""The config topics a variant may dictate for the providers it pulls in.

A round deploys a provider once, so the role that pulls it in is the only
place that can say how lean it has to be. A variant entry may therefore carry
any application config topic under the service it depends on:

    services:
      openwebui:
        enabled: true
        shared: true
        services: null        # brings nothing along
        addons:
          whisper:
            enabled: false    # everything else in addons survives

A mapping deep-merges, so naming one key changes that key and nothing else.
``null`` empties the topic, which is the only way to say "bring nothing":
merged, an empty mapping is a no-op and would leave exactly the services the
round was trying to shed.

YAML writes null three ways - ``null``, ``~``, and a key with nothing after
it - so a half-typed line empties a topic rather than being ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

CONFIG_TOPICS = frozenset(
    {
        "addons",
        "csp",
        "domains",
        "group_id",
        "info",
        "mcp",
        "networks",
        "packages",
        "rbac",
        "secrets",
        "server",
        "services",
        "tests",
        "users",
    }
)


def apply_topic(base_value: Any, override_value: Any) -> Any:
    """Return a provider's topic after one override is applied.

    Args:
        base_value: what the provider declares for the topic today.
        override_value: what the pulling role demands.

    ``None`` empties the topic and is normalised to ``{}``: the closure
    resolver skips a non-mapping payload, so leaving the bare ``None`` would
    silently keep the services it was meant to drop.
    """
    if override_value is None:
        return {}
    return _deep_merge(base_value, override_value)


def provider_of(service_key: str, service_registry: Mapping) -> str:
    """Return the role providing ``service_key``, or "" when unregistered.

    Args:
        service_key: a first-level key of a role's services map.
        service_registry: the project-wide service registry.
    """
    entry = service_registry.get(service_key)
    if not isinstance(entry, Mapping):
        return ""
    role = entry.get("role")
    return str(role).strip() if role else ""


def overridden_providers(roles_dir: str | Path) -> dict[tuple[str, int], set[str]]:
    """Return ``{(role, variant index): {provider role, ...}}`` across every variant.

    Args:
        roles_dir: roles directory the variants and service registry are read from.

    A variant that dictates a provider's config does not deploy that provider as
    the provider declares it, so nothing about that run states what the provider
    does on its own. Callers that reason about coverage need to know which pairs
    those are before they credit one role's deploy to another.
    """
    roles_root = Path(roles_dir)
    registry = build_service_registry_from_roles_dir(roles_root)
    found: dict[tuple[str, int], set[str]] = {}
    for path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_VARIANTS}")):
        role = path.parent.parent.name
        variants = load_yaml_any(str(path), default_if_missing=[]) or []
        for index, variant in enumerate(variants):
            services = (variant or {}).get("services") or {}
            if not isinstance(services, Mapping):
                continue
            for service_key, entry in services.items():
                if not isinstance(entry, Mapping) or not CONFIG_TOPICS & set(entry):
                    continue
                target = provider_of(str(service_key), registry)
                if target and target != role:
                    found.setdefault((role, index), set()).add(target)
    return found
