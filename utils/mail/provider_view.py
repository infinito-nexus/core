"""The applications view of the onion-serving mail provider host, and its carriers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from utils.cache.carrier import (
    APPLICATIONS_RENDERED_FACT,
    PROVIDER_VIEW_RENDERED_FACT,
    _carried_applications,
    _carried_provider_view,
    merged_applications_cache_key,
)


def _provider_carrier(
    variables: Mapping[str, Any], host: str
) -> Mapping[str, Any] | None:
    hostvars = variables.get("hostvars")
    raw_get = getattr(hostvars, "raw_get", None)
    try:
        host_vars = raw_get(host) if callable(raw_get) else hostvars[host]
    except (KeyError, TypeError):
        return None
    if not isinstance(host_vars, Mapping):
        return None
    carrier = host_vars.get(APPLICATIONS_RENDERED_FACT)
    return carrier if isinstance(carrier, Mapping) else None


def provider_view(
    variables: Mapping[str, Any], provider: str
) -> tuple[str, dict[str, Any]] | None:
    """This host's variables as the onion-serving provider host sees its groups.

    Args:
        variables: Ansible variables of the current host.
        provider: the active mail provider role.

    Returns:
        ``(provider host, view)``, or ``None`` when no host of *provider*
        is in ``svc-net-tor``.
    """
    groups = variables.get("groups") or {}
    tor_hosts = set(groups.get("svc-net-tor") or [])
    provider_hosts = [h for h in groups.get(provider) or [] if h in tor_hosts]
    if not provider_hosts:
        return None
    own_groups = list(variables.get("group_names") or [])
    fallback = own_groups + [
        g for g in ("svc-net-tor", provider) if g not in own_groups
    ]
    try:
        provider_vars = variables["hostvars"][provider_hosts[0]]
        provider_groups = provider_vars["group_names"]
    except (KeyError, TypeError):
        provider_vars = {}
        provider_groups = fallback
    view = dict(variables)
    view["group_names"] = list(provider_groups or fallback)
    if provider_vars.get("NETWORK_MODE"):
        view["NETWORK_MODE"] = provider_vars["NETWORK_MODE"]
    return provider_hosts[0], view


def view_id(host: str, view: Mapping[str, Any]) -> list[str]:
    """Identify a provider view.

    Args:
        host: the provider host the view was built for.
        view: the view from `provider_view`.

    Returns:
        ``[host, NETWORK_MODE]``.
    """
    return [str(host), str(view.get("NETWORK_MODE") or "")]


def view_carrier(
    variables: Mapping[str, Any],
    host: str,
    view: Mapping[str, Any],
    roles_dir: str | None,
) -> Mapping[str, Any] | None:
    """Return a carrier that still matches *view*, or ``None``.

    Args:
        variables: Ansible variables of the current host.
        host: the provider host *view* was built for.
        view: the view from `provider_view`.
        roles_dir: roles tree the key is computed over; the repository's when ``None``.

    Returns:
        This host's parked provider view when its key and `view_id` match,
        else the provider host's own applications carrier when its key
        matches, else ``None``.
    """
    key = merged_applications_cache_key(view, roles_dir=roles_dir)
    if _carried_provider_view(variables, key) is not None and list(
        variables[PROVIDER_VIEW_RENDERED_FACT].get("view") or []
    ) == view_id(host, view):
        return variables[PROVIDER_VIEW_RENDERED_FACT]
    provider = _provider_carrier(variables, host)
    if (
        provider is not None
        and _carried_applications({APPLICATIONS_RENDERED_FACT: provider}, key)
        is not None
    ):
        return provider
    return None
