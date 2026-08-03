"""Shared Ansible-side assembly for the network lookup plugins.

Every one of them needs the same four things before it can call into
:mod:`utils.networks.render`: the resolved variables, the deployment mode, a
service registry built from the merged applications, and closures over the
``config`` and ``database`` lookups. Building that once means a change to how
the registry or the closures are obtained cannot reach one lookup and miss
another.

Args of :func:`build_context` are documented on the function.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ansible.plugins.loader import lookup_loader

from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def resolve_var(templar: Any, value: Any) -> Any:
    """Template ``value`` when a templar is available, else pass it through.

    Args:
        templar: the plugin's templar, or None.
        value: raw variable value.
    """
    if templar is None:
        return value
    with contextlib.suppress(Exception):
        return templar.template(value)
    return value


@dataclass(frozen=True)
class NetworkLookupContext:
    """What a network lookup needs to call the renderers."""

    vars: dict[str, Any]
    templar: Any
    deployment_mode: str
    registry: dict[str, dict[str, Any]]
    lookup_config: Callable[[str, str, Any], Any]
    lookup_database: Callable[[str, str], Any]


def build_context(
    lookup: Any,
    variables: dict[str, Any] | None,
    *,
    honour_mode_force: bool = True,
) -> NetworkLookupContext:
    """Assemble the shared context for a network lookup.

    Args:
        lookup: the LookupModule instance, for its templar and loader.
        variables: the variables Ansible passed to ``run``.
        honour_mode_force: let ``compose_mode_force`` override DEPLOYMENT_MODE.
    """
    templar = getattr(lookup, "_templar", None)
    vars_ = variables or getattr(templar, "available_variables", {}) or {}

    deployment_mode = str(resolve_var(templar, vars_.get("DEPLOYMENT_MODE", "compose")))
    if honour_mode_force:
        mode_force = resolve_var(templar, vars_.get("compose_mode_force", ""))
        deployment_mode = str(mode_force or deployment_mode).strip()

    applications = lookup_loader.get(
        "applications", loader=lookup._loader, templar=templar
    ).run([], variables=vars_)[0]

    config_lookup = lookup_loader.get("config", loader=lookup._loader, templar=templar)
    database_lookup = lookup_loader.get(
        "database", loader=lookup._loader, templar=templar
    )

    def _lookup_config(app: str, path: str, default: Any) -> Any:
        return config_lookup.run([app, path, default], variables=vars_)[0]

    def _lookup_database(app: str, key: str) -> Any:
        return database_lookup.run([app, key], variables=vars_)[0]

    return NetworkLookupContext(
        vars=vars_,
        templar=templar,
        deployment_mode=deployment_mode,
        registry=build_service_registry_from_applications(applications),
        lookup_config=_lookup_config,
        lookup_database=_lookup_database,
    )
