"""The network axis of the CI deploy matrix: which node network modes a row may take.

Separate from :mod:`utils.github.variant.axes` because it answers a different
question. ``axes`` decides which combination a row takes this sweep; this
module decides which network modes exist for that row at all -- read off the
role's ``meta/services.yml`` and ``meta/networks.yml``, off the covered
variant, off the deploy mode, and off the run's own ``network`` input.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import (
    CLEARNET,
    MULTI,
    NETWORKS,
    NODE_MODES,
    TOR,
    role_reachability,
)
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

ROLES_DIR = PROJECT_ROOT / "roles"

AUTO = "auto"

TOR_SERVICE = "tor"

NETWORK_INPUTS = (AUTO, *NODE_MODES)

NETWORK_DEPLOY_MODES = ("swarm", "compose")


def _meta(app: str, filename: str) -> dict[str, Any]:
    path = ROLES_DIR / app / filename
    if not path.exists():
        return {}
    try:
        loaded = load_yaml_any(path) or {}
    except Exception:  # noqa: BLE001  malformed role meta must not break the matrix
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _tor_flag(config: Mapping[str, Any]) -> Any:
    """The ``services.tor.enabled`` value of one config, ``None`` without a bond."""
    services = config.get("services") if isinstance(config, dict) else None
    tor = services.get("tor") if isinstance(services, dict) else None
    return tor.get("enabled") if isinstance(tor, dict) else None


def _row_tor_flag(
    app: str,
    variant: int | None,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> Any:
    """The row's ``services.tor.enabled``: the covered variant's value, else
    the role's base ``meta/services.yml`` one; ``None`` without a Tor bond.
    Roles pin the gate ``true`` in variant 0 and ``false`` in the rest."""
    declared = (variants_per_app or {}).get(app) or []
    if variant is None or not 0 <= variant < len(declared):
        return _tor_flag({"services": _meta(app, ROLE_FILE_META_SERVICES)})
    return _tor_flag(declared[variant])


def _reachability(
    app: str,
    variant: int | None,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[tuple[str, ...], bool]:
    declared = (variants_per_app or {}).get(app) or []
    config: Mapping[str, Any] = {}
    if variant is not None and 0 <= variant < len(declared):
        config = declared[variant]
    if not isinstance(config, dict) or "networks" not in config:
        config = {"networks": _meta(app, ROLE_FILE_META_NETWORKS)}
    return role_reachability(config, app=app)


def tor_provider() -> str | None:
    """Application id of the role providing the ``tor`` service, ``None`` if
    the registry names none. Resolved rather than hardcoded so renaming the
    provider role cannot leave the matrix pointing at a dead id."""
    entry = build_service_registry_from_roles_dir(ROLES_DIR).get(TOR_SERVICE) or {}
    role = entry.get("role")
    return role if isinstance(role, str) and role else None


def row_pulls_tor(row: Mapping[str, Any]) -> bool:
    """Whether a discovery row's ``services`` closure takes the Tor provider in."""
    return tor_provider() in (row.get("services") or ())


def row_states(
    app: str,
    variant: int | None = None,
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    pulls_tor: bool = False,
) -> tuple[str, ...]:
    """Every node network mode the row's role can be served in.

    Args:
        app: application id.
        variant: the row's variant index; ``None`` for a role declaring none.
        variants_per_app: rendered variant configs per app.
        pulls_tor: the row's deploy takes the Tor provider in
            (:func:`row_pulls_tor`).

    Returns:
        ``clearnet`` alone when the covered variant pins the Tor gate to a
        literal false, or when the role has no Tor bond and nothing pulls the
        provider in. ``clearnet`` and ``multi`` for a role without a bond whose
        deploy pulls the provider in anyway: the node then runs Tor while the
        role stays on clearnet. Otherwise, a reactive Jinja gate included, the
        modes whose networks all lie inside the role's ``reachability.modes``,
        without ``multi`` for a ``single_mode`` role and without ``clearnet``
        for the Tor provider, which disabling Tor would strip out of its own
        deploy.
    """
    flag = _row_tor_flag(app, variant, variants_per_app)
    if flag is None:
        return (CLEARNET, MULTI) if pulls_tor else (CLEARNET,)
    if flag is False:
        return (CLEARNET,)
    modes, single_mode = _reachability(app, variant, variants_per_app)
    allowed = modes or tuple(NETWORKS)
    states = [
        state
        for state, networks in NODE_MODES.items()
        if all(name in allowed for name in networks)
    ]
    if single_mode:
        states = [state for state in states if state != MULTI]
    if app == tor_provider():
        states = [state for state in states if state != CLEARNET]
    return tuple(states)


def resolve_network_input(raw: str | None = None) -> str:
    """Network axis input from ``INFINITO_NETWORK``; unknown or empty means ``auto``.

    Args:
        raw: explicit value; ``None`` reads the environment.

    Returns:
        one of :data:`NETWORK_INPUTS`.
    """
    if raw is None:
        raw = os.environ.get("INFINITO_NETWORK")
    value = (raw or "").strip().lower()
    return value if value in NETWORK_INPUTS else AUTO


def network_states(
    mode: str, *, states: Sequence[str], network_input: str
) -> list[str]:
    """The network modes one deploy *mode* is worth running for a row.

    Args:
        mode: the deploy mode the row runs in.
        states: the network modes the row's role can be served in
            (:func:`row_states`).
        network_input: the run's network axis.

    Returns:
        Every state under ``auto``, the pinned state alone when the row can
        take it and nothing otherwise. A deploy mode that carries no network
        axis (host) only ever yields ``clearnet``.
    """
    if mode not in NETWORK_DEPLOY_MODES:
        states = [state for state in states if state == CLEARNET]
    if network_input == AUTO:
        return list(states)
    return [network_input] if network_input in states else []


def combinations(
    offered: Sequence[str], *, states: Sequence[str], network_input: str
) -> list[tuple[str, str]]:
    """Every ``(mode, network)`` pair a priority row is deployed in.

    Priority rows are the ones a run must not sample: they cover the whole
    cross-product of the modes their role offers and the network modes each
    of those deploy modes can take, in one sweep.
    """
    return [
        (mode, state)
        for mode in offered
        for state in network_states(mode, states=states, network_input=network_input)
    ]


def disabled_services(state: str) -> str:
    """The ``disable`` tokens a row deploys with: Tor goes when the node
    serves no network that needs it."""
    return "" if TOR in NODE_MODES[state] else TOR_SERVICE
