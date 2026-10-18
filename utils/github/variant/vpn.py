from __future__ import annotations

import os

VPN_MODES = ("auto", "enforced", "disabled")

VPN_DEPLOY_MODES = ("swarm",)


def resolve_vpn_mode(raw: str | None = None) -> str:
    """Mesh axis mode from ``INFINITO_VPN``.

    Args:
        raw: explicit value; ``None`` reads the environment.

    Returns:
        one of :data:`VPN_MODES`, ``auto`` for an unknown or empty value.
    """
    if raw is None:
        raw = os.environ.get("INFINITO_VPN")
    value = (raw or "").strip().lower()
    return value if value in VPN_MODES else "auto"


def vpn_states(mode: str, *, vpn_mode: str = "auto") -> list[bool]:
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
    return (position // 2 + sweep // 4) % 2 == 0


def rotated_vpn(
    mode: str,
    *,
    position: int,
    sweep: int,
    pin: bool | None = None,
    vpn_mode: str = "auto",
) -> bool:
    if mode not in VPN_DEPLOY_MODES:
        return False
    if vpn_mode in ("enforced", "disabled"):
        return vpn_mode == "enforced"
    if pin is not None:
        return pin
    return wants_vpn(position, sweep)
