"""The WireGuard-mesh axis of a deploy row.

Split out beside ``tor.py`` for the same reason: one axis, its modes, its
rotation and its glyph pairing belong together rather than spread through the
assigner.

A swarm deploy runs either over the mesh or straight over the underlay, and
both have to keep working -- the mesh joins physically separated clusters, so a
single-site swarm has no use for it and must not depend on it. Rotating the
axis proves both arms instead of proving one and assuming the other.
"""

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


def wants_vpn(position: int, sweep: int) -> bool:
    """Whether a swarm row carries the mesh this sweep.

    Quartered on ``sweep // 4`` so it flips in step with neither the mode
    rotation nor the onion: a row walks every mode/tor/vpn combination over
    eight sweeps instead of re-proving the same pairing.
    """
    return (position + sweep // 4) % 2 == 0


def rotated_vpn(
    mode: str,
    *,
    position: int,
    sweep: int,
    pin: bool | None = None,
    vpn_mode: str = "auto",
) -> bool:
    """The single mesh state a regular row takes this sweep.

    A pin replaces the rotation, and a run that holds the axis replaces both:
    an operator who asked for a whole sweep on one side means it.
    """
    if mode not in VPN_DEPLOY_MODES:
        return False
    if vpn_mode in ("enforced", "disabled"):
        return vpn_mode == "enforced"
    if pin is not None:
        return pin
    return wants_vpn(position, sweep)
