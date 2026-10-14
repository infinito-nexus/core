"""Networks an application is served on, and the registry that defines them.

A node runs in one network mode (``clearnet``, ``tor`` or ``multi``) and a
role narrows it through ``reachability`` in its ``meta/networks.yml``. Every
other module asks this one which network a domain belongs to instead of
testing a suffix of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Network:
    """One network a vhost can be served on.

    Args:
        name: id used in ``reachability.modes`` and in ``NETWORK_MODE``.
        label: suffix of the ``<key>_<label>`` entry a named-canonical domain
            dict gains for this network.
        provider: role that brings the network to a node, ``None`` for clearnet.
        suffix: domain suffix that identifies the network, ``None`` for clearnet.
        tls: whether vhosts of this network terminate TLS.
        browser_proxy: whether a browser needs the provider's proxy to reach it.
        probe_timeout: seconds a health probe waits for one of its vhosts.
    """

    name: str
    label: str
    provider: str | None
    suffix: str | None
    tls: bool
    browser_proxy: bool
    probe_timeout: int


CLEARNET = "clearnet"
TOR = "tor"
MULTI = "multi"

NETWORKS: dict[str, Network] = {
    CLEARNET: Network(CLEARNET, "clearnet", None, None, True, False, 10),
    TOR: Network(TOR, "onion", "svc-net-tor", ".onion", False, True, 30),
}

RESERVED_NETWORKS: tuple[str, ...] = ("handshake",)

NODE_MODES: dict[str, tuple[str, ...]] = {
    CLEARNET: (CLEARNET,),
    TOR: (TOR,),
    MULTI: (CLEARNET, TOR),
}


def _host(domain: Any) -> str:
    return str(domain or "").strip().lower().rstrip(".")


def network_of(domain: Any) -> str:
    """Return the name of the network ``domain`` belongs to.

    Args:
        domain: host name, with or without a trailing dot.

    Returns:
        The first registry network whose suffix the host carries, else
        ``clearnet``.
    """
    host = _host(domain)
    for network in NETWORKS.values():
        if network.suffix and host.endswith(network.suffix):
            return network.name
    return CLEARNET


def is_network(domain: Any, name: str) -> bool:
    """Return whether ``domain`` belongs to the network called ``name``."""
    return network_of(domain) == name


def network(name: str) -> Network:
    """Return the registry entry for ``name``.

    Raises:
        ValueError: ``name`` is reserved or unknown.
    """
    if name in RESERVED_NETWORKS:
        raise ValueError(f"network '{name}' is reserved and not implemented yet")
    try:
        return NETWORKS[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown network '{name}'; known: {', '.join(NETWORKS)}"
        ) from exc


def sibling_domain(domain: Any, target: str, primary: str, node: str) -> str | None:
    """Return the name ``domain`` carries in the network ``target``.

    Clearnet names live under ``primary``; a tor name swaps that suffix for
    the node onion address.

    Args:
        domain: host name in any registry network.
        target: network to translate into.
        primary: the node's ``DOMAIN_PRIMARY``.
        node: the node onion address.

    Returns:
        The translated host, ``domain`` itself when it already belongs to
        ``target``, or ``None`` when it lies outside both suffixes or the
        node has no address in the other network.
    """
    host = _host(domain)
    base = _host(primary)
    onion = _host(node)
    network(target)
    if network_of(host) == target:
        return host
    if not base or not onion:
        return None
    if target == TOR:
        if host == base:
            return onion
        if base and host.endswith("." + base):
            return host[: -len(base)] + onion
        return None
    if host == onion:
        return base
    if onion and host.endswith("." + onion):
        return host[: -len(onion)] + base
    return None


def resolve_node_mode(raw: Any, *, tor_provided: bool) -> str:
    """Return the node's network mode.

    Args:
        raw: ``NETWORK_MODE`` as declared; empty derives the default.
        tor_provided: whether ``svc-net-tor`` runs on the node with a node
            onion address.

    Returns:
        ``multi`` when empty and Tor is provided, ``clearnet`` when empty
        otherwise, the declared mode else.

    Raises:
        ValueError: the mode is unknown, or it needs Tor on a node without it.
    """
    value = str(raw or "").strip().lower()
    if not value:
        return MULTI if tor_provided else CLEARNET
    if value not in NODE_MODES:
        raise ValueError(
            f"NETWORK_MODE '{value}' is unknown; known: {', '.join(NODE_MODES)}"
        )
    if TOR in NODE_MODES[value] and not tor_provided:
        raise ValueError(
            f"NETWORK_MODE '{value}' needs svc-net-tor with a node onion on this node"
        )
    return value


def role_reachability(
    app_config: Any, *, app: str = ""
) -> tuple[tuple[str, ...], bool]:
    """Read ``networks.reachability`` of one application.

    Args:
        app_config: the application's merged config.
        app: application id, for error messages.

    Returns:
        ``(modes, single_mode)``; empty ``modes`` means every network.

    Raises:
        TypeError: ``reachability`` is not a mapping, ``modes`` not a list or
            ``single_mode`` not a boolean.
        ValueError: a mode is not a registry network.
    """
    networks = app_config.get("networks") if isinstance(app_config, Mapping) else None
    reach = networks.get("reachability") if isinstance(networks, Mapping) else None
    if reach is None:
        return (), False
    if not isinstance(reach, Mapping):
        raise TypeError(f"{app}: networks.reachability must be a mapping")
    modes = reach.get("modes") or []
    if not isinstance(modes, list | tuple):
        raise TypeError(f"{app}: networks.reachability.modes must be a list")
    unknown = [mode for mode in modes if mode not in NETWORKS]
    if unknown:
        raise ValueError(
            f"{app}: networks.reachability.modes has unknown network(s) "
            f"{unknown}; known: {', '.join(NETWORKS)}"
        )
    single = reach.get("single_mode", False)
    if not isinstance(single, bool):
        raise TypeError(f"{app}: networks.reachability.single_mode must be a boolean")
    return tuple(dict.fromkeys(modes)), single


def allowed_networks(
    app_config: Any, *, tor_enabled: bool, app: str = ""
) -> tuple[tuple[str, ...], bool]:
    """Return the networks a role may be served on, and its ``single_mode``.

    Args:
        app_config: the application's merged config.
        tor_enabled: the rendered ``services.tor.enabled`` of the role.
        app: application id, for error messages.

    Returns:
        ``(networks, single_mode)`` with ``networks`` in registry order.
    """
    modes, single = role_reachability(app_config, app=app)
    networks = tuple(name for name in NETWORKS if not modes or name in modes)
    if not tor_enabled:
        networks = tuple(name for name in networks if name != TOR)
    return networks, single


def effective_networks(
    node_mode: str, allowed: tuple[str, ...], single_mode: bool, *, app: str = ""
) -> tuple[str, ...]:
    """Return the networks a role is served on, canonical network first.

    Args:
        node_mode: the resolved node mode.
        allowed: networks the role may be served on.
        single_mode: whether the role is reachable under one domain only.
        app: application id, for error messages.

    Returns:
        The node's networks the role allows, reduced to ``tor`` (else the
        first one) when ``single_mode`` is set.

    Raises:
        ValueError: the role allows none of the node's networks.
    """
    served = tuple(name for name in NODE_MODES[node_mode] if name in allowed)
    if single_mode and len(served) > 1:
        served = (TOR,) if TOR in served else served[:1]
    if not served:
        raise ValueError(
            f"{app}: allows {list(allowed)} but the node runs in '{node_mode}' "
            f"mode ({', '.join(NODE_MODES[node_mode])}); set NETWORK_MODE or "
            f"networks.reachability accordingly"
        )
    return served
