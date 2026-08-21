"""Resolve a single ``services.<key>.<field>`` with provider fallback.

A consuming role MAY override a shared service's config field in its own
``meta/services.yml`` ``services.<key>`` block. When it does not, the value
falls back to the *provider* role's native declaration — the role whose entity
name is ``<key>`` (e.g. ``svc-net-tor`` for ``tor``). This keeps provider
defaults (e.g. ``tor.exclusive`` / ``tor.primary``) in one place while every
consumer stays free to override the field per app.
"""

from __future__ import annotations

from typing import Any

from utils.roles.applications.config import get
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)

_MISSING = object()


def _service_entry(
    applications: dict[str, Any],
    application_id: str,
    service_key: str,
) -> dict[str, Any]:
    entry = get(
        applications=applications,
        application_id=application_id,
        config_path=f"services.{service_key}",
        strict=False,
        default={},
        skip_missing_app=True,
    )
    return entry if isinstance(entry, dict) else {}


def resolve_service_config(
    applications: dict[str, Any],
    application_id: str,
    service_key: str,
    config_key: str,
    default: Any = None,
    *,
    service_registry: dict[str, Any] | None = None,
) -> Any:
    """Return ``services.<service_key>.<config_key>`` for ``application_id``.

    Resolution order:
      1. the consuming role's own override, when it declares ``config_key``;
      2. the provider role's native value (role whose entity is ``service_key``);
      3. ``default``.

    Pass ``service_registry`` to reuse a registry already built by the caller
    (avoids rebuilding it once per lookup inside a loop).
    """
    consumer = _service_entry(applications, application_id, service_key)
    if config_key in consumer:
        return consumer[config_key]

    registry = (
        service_registry
        if service_registry is not None
        else build_service_registry_from_applications(applications)
    )
    entry = registry.get(service_key) or {}
    provider = entry.get("role")
    if isinstance(provider, str) and provider and provider != application_id:
        provider_cfg = _service_entry(applications, provider, service_key)
        if config_key in provider_cfg:
            return provider_cfg[config_key]
    return default
