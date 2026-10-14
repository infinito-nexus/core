"""Domain-name cache: canonical-domains map derived from merged apps.

Owns `_MERGED_DOMAINS_CACHE`. Public API: `get_merged_domains`. The
domain map is intentionally derived from the applications view rather
than living in a parallel top-level overrides path. Per-app domain
declarations live in `applications.<app>.domains` and flow through the
regular applications-merge pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.networks.reachability import (
    CLEARNET,
    NODE_MODES,
    TOR,
    allowed_networks,
    effective_networks,
    network,
    resolve_node_mode,
    sibling_domain,
)

from .base import (
    _RENDER_GUARD,
    _cache_key,
    _resolve_roles_dir,
    _stable_variables_signature,
)

if TYPE_CHECKING:
    import os

_MERGED_DOMAINS_CACHE: dict[tuple, dict[str, Any]] = {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _resolved_flag(
    value: Any,
    *,
    app: str,
    name: str,
    templar: Any,
    variables: Any,
    apps: Any,
) -> bool:
    """A tor service flag as a boolean, never as the text of its own template.

    ``services.tor.*`` is declared as Jinja in 99 of the 105 roles that carry
    it. When this map is built from an applications tree that is still being
    rendered (``utils.cache.applications`` returns the raw tree while its own
    render is in flight) the flag arrives as its source text, which every
    boolean coercion reads as False. The onion injection would then silently
    not happen and the clearnet domain would be frozen into whatever value the
    render was producing.

    Args:
        value: the declared flag, rendered or not.
        app: application id, for the error message.
        name: flag name under ``services.tor``, for the error message.
        templar: templar to render with; ``None`` renders nothing.
        variables: scope the template resolves against.
        apps: applications tree seeded into the nested render.

    Returns:
        The flag as a boolean.

    Raises:
        ValueError: the flag still carries template text after rendering.
    """
    if isinstance(value, str) and ("{{" in value or "{%" in value):
        from utils.cache.base import _render_with_templar

        value = _render_with_templar(
            value, templar=templar, variables=variables, raw_applications=apps
        )
    if isinstance(value, str) and ("{{" in value or "{%" in value):
        raise ValueError(
            f"get_merged_domains: '{app}' services.tor.{name} stayed template "
            f"text ({value!r}). Reading it as a boolean would drop the onion "
            "domains without saying so."
        )
    return _as_bool(value)


def _render_plain(raw: Any, name: str) -> Any:
    from utils.templating.ansible import render_ansible_strict

    if isinstance(raw, str) and ("{{" in raw or "{%" in raw):
        return render_ansible_strict(
            templar=None,
            raw=raw,
            var_name=name,
            err_prefix="get_merged_domains",
            variables={},
        )
    return raw


def node_onion_of(apps: Any, variables: Any) -> str:
    """Return the node onion address when this host runs ``svc-net-tor``.

    Args:
        apps: merged applications tree.
        variables: host variables carrying ``group_names``.

    Returns:
        The address from ``svc-net-tor``'s ``services.tor.node``, or ``""``
        when the provider is not deployed on this host.
    """
    if network(TOR).provider not in ((variables or {}).get("group_names") or []):
        return ""
    node_raw = (
        ((apps.get(network(TOR).provider) or {}).get("services") or {}).get("tor") or {}
    ).get("node")
    return str(_render_plain(node_raw or "", "services.tor.node") or "").strip()


def node_network_mode(variables: Any, node_onion: str) -> str:
    """Return the resolved ``NETWORK_MODE`` of this host.

    Args:
        variables: host variables carrying ``NETWORK_MODE``.
        node_onion: the node onion address, empty without Tor.
    """
    return resolve_node_mode(
        _render_plain((variables or {}).get("NETWORK_MODE") or "", "NETWORK_MODE"),
        tor_provided=bool(node_onion),
    )


def _serve_list(
    domains: list[Any], networks: tuple[str, ...], primary: str, node_onion: str
) -> list[Any]:
    if TOR not in networks:
        return list(domains)
    onion = [
        sibling
        for d in domains
        if (sibling := sibling_domain(str(d), TOR, primary, node_onion))
    ]
    if CLEARNET not in networks:
        return onion or list(domains)
    return list(domains) + [o for o in onion if o not in domains]


def _serve_dict(
    domains: dict[str, Any], networks: tuple[str, ...], primary: str, node_onion: str
) -> dict[str, Any]:
    if TOR not in networks:
        return dict(domains)
    if CLEARNET not in networks:
        return {
            key: (sibling_domain(str(value), TOR, primary, node_onion) or value)
            for key, value in domains.items()
        }
    label = network(TOR).label
    siblings: dict[str, Any] = {}
    for key, value in domains.items():
        sibling = sibling_domain(str(value), TOR, primary, node_onion)
        if sibling and sibling != value:
            siblings[f"{key}_{label}"] = sibling
    return {**domains, **siblings}


def _inject_network_siblings(
    merged: dict[str, Any],
    apps: dict[str, Any],
    primary: str,
    node_onion: str,
    node_mode: str,
    *,
    deployed: Any = (),
    templar: Any = None,
    variables: Any = None,
) -> dict[str, Any]:
    """Serve every application on the networks it resolves to on this node.

    Args:
        merged: canonical domains per application.
        apps: merged applications tree.
        primary: the node's ``DOMAIN_PRIMARY``.
        node_onion: the node onion address, empty on a node without Tor.
        node_mode: the resolved ``NETWORK_MODE``.
        deployed: application ids deployed on this host; only their mismatch
            fails, the rest keep their domains.
        templar: templar rendering the ``services.tor.enabled`` flags.
        variables: scope those flags resolve against.

    Returns:
        Domains per application with the canonical network first. A role
        without a ``tor`` service keeps its domains on every node.

    Raises:
        ValueError: a deployed role allows none of the node's networks.
    """
    out: dict[str, Any] = {}
    for app, domains in merged.items():
        config = apps.get(app) or {}
        tor = (config.get("services") or {}).get("tor")
        if not isinstance(domains, (list, dict)) or not isinstance(tor, dict):
            out[app] = domains
            continue
        tor_enabled = TOR in NODE_MODES[node_mode] and _resolved_flag(
            tor.get("enabled"),
            app=app,
            name="enabled",
            templar=templar,
            variables=variables,
            apps=apps,
        )
        allowed, single_mode = allowed_networks(
            config, tor_enabled=tor_enabled, app=app
        )
        try:
            networks = effective_networks(node_mode, allowed, single_mode, app=app)
        except ValueError:
            if app in deployed:
                raise
            out[app] = domains
            continue
        if isinstance(domains, dict):
            out[app] = _serve_dict(domains, networks, primary, node_onion)
        else:
            out[app] = _serve_list(domains, networks, primary, node_onion)
    return out


def get_merged_domains(
    *,
    variables: dict[str, Any] | None = None,
    roles_dir: str | os.PathLike[str] | None = None,
    templar: Any = None,
) -> dict[str, Any]:
    """Build the canonical-domain map lazily from the merged applications view.

    The result is canonical_domains_map(applications, DOMAIN_PRIMARY).
    Per-app domain declarations live in `applications.<app>.domains`
    (canonical/aliases) and flow through the regular applications-merge
    pipeline.

    Cached keyed on (roles_dir, variables_signature, render_state). A read
    issued while the applications render is in progress sees the unrendered
    tree, whose service flags are still Jinja strings; its map is cached under
    its own key so the render's own call sites reuse it without it ever being
    served as the finished map. The tor flags are rendered before they are
    read (``_resolved_flag``), so that mid-render map carries the same onion
    domains the finished one does.
    """
    from plugins.filter.canonical_domains_map import (
        FilterModule as _CanonicalDomainsFilter,
    )

    from .applications import get_merged_applications

    variables = variables or {}
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)

    cache_key = (
        _cache_key(resolved_roles_dir),
        _stable_variables_signature(variables),
        bool(getattr(_RENDER_GUARD, "applications", False)),
    )
    cached = _MERGED_DOMAINS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    primary_domain = (
        variables.get("DOMAIN_PRIMARY") or variables.get("SYSTEM_EMAIL_DOMAIN") or ""
    )
    if not primary_domain:
        raise ValueError(
            "get_merged_domains: DOMAIN_PRIMARY (or SYSTEM_EMAIL_DOMAIN fallback) "
            "must be set in variables."
        )

    primary_domain = _render_plain(primary_domain, "DOMAIN_PRIMARY")

    apps = get_merged_applications(
        variables=variables,
        roles_dir=roles_dir,
        templar=templar,
    )

    filter_instance = _CanonicalDomainsFilter()
    merged = filter_instance.canonical_domains_map(apps, primary_domain)

    node_onion = node_onion_of(apps, variables)
    node_mode = node_network_mode(variables, node_onion)
    merged = _inject_network_siblings(
        merged,
        apps,
        str(primary_domain),
        node_onion,
        node_mode,
        deployed=variables.get("group_names") or [],
        templar=templar,
        variables=variables,
    )

    _MERGED_DOMAINS_CACHE[cache_key] = merged
    return merged


def _reset() -> None:
    _MERGED_DOMAINS_CACHE.clear()
