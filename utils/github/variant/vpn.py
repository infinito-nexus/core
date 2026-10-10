"""The WireGuard-mesh axis of a deploy row."""

from __future__ import annotations

import os

VPN_MODES = ("auto", "enforced", "disabled")
"""How a run treats the axis. ``auto`` rotates it, the other two hold every
swarm row on one side so a whole sweep can be spent proving that side. There is
no ``exclusive``: every swarm row can take the mesh, so there is nothing to
drop."""

VPN_DEPLOY_MODES = ("swarm",)
"""Modes the mesh is meaningful in. Compose is a single host, so there is
nothing to tunnel between and the axis is always off there."""

MESH_GLYPH_MODES = VPN_DEPLOY_MODES
"""Modes whose label carries a mesh glyph at all. A compose title stays as it
was, so the existing job names do not all churn for an axis they never take."""


def resolve_vpn_mode(raw: str | None = None) -> str:
    """Mesh axis mode from ``INFINITO_VPN``; unknown or empty means ``auto``.

    Args:
        raw: explicit value; ``None`` reads the environment.

    Returns:
        one of :data:`VPN_MODES`.
    """
    if raw is None:
        raw = os.environ.get("INFINITO_VPN")
    value = (raw or "").strip().lower()
    return value if value in VPN_MODES else "auto"


def vpn_states(mode: str, *, vpn_mode: str = "auto") -> list[bool]:
    """The mesh states *mode* is worth running for a priority row."""
    if mode not in VPN_DEPLOY_MODES:
        return [False]
    if vpn_mode == "enforced":
        return [True]
    if vpn_mode == "disabled":
        return [False]
    return [False, True]


def pinned_vpn_states(
    mode: str, *, pin: bool | None = None, vpn_mode: str = "auto"
) -> list[bool]:
    """The mesh states a priority row takes, global axis ahead of the pin.

    Args:
        mode: the deploy mode of the row.
        pin: the state the row asked for, or None for every state.
        vpn_mode: the run's axis mode.
    """
    states = vpn_states(mode, vpn_mode=vpn_mode)
    if vpn_mode in ("enforced", "disabled") or pin is None:
        return states
    return [state for state in states if state == pin]


def wants_vpn(position: int, sweep: int) -> bool:
    """Whether a swarm row carries the mesh this sweep."""
    return (position + sweep // 4) % 2 == 0


def rotated_vpn(
    mode: str,
    *,
    position: int,
    sweep: int,
    pin: bool | None = None,
    vpn_mode: str = "auto",
) -> bool:
    """The single mesh state a regular row takes this sweep."""
    if mode not in VPN_DEPLOY_MODES:
        return False
    if vpn_mode in ("enforced", "disabled"):
        return vpn_mode == "enforced"
    if pin is not None:
        return pin
    return wants_vpn(position, sweep)
