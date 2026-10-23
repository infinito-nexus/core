"""Prove a selection token's pins against what the row and the run permit.

Separate from :mod:`utils.github.variant.axes`, which decides the axes of a
row that carries no pin: this module only refuses the combinations a pin
asks for and the row cannot give.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.github.variant.network import network_states
from utils.github.variant.pools import ARCHITECTURES
from utils.github.variant.vpn import VPN_DEPLOY_MODES, pinned_vpn_states
from utils.roles.display import VARIANT_SEPARATOR
from utils.roles.meta_lookup import get_role_architectures

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["check_pins", "row_architectures"]


def _reject(app: str, variant: str, reason: str) -> None:
    """Abort on a selection the row cannot satisfy.

    Raises:
        SystemExit: always. A pin the row cannot take is an operator mistake,
            and dropping the row instead would report a green run for a
            combination that never ran.
    """
    shard = f"{VARIANT_SEPARATOR}{variant}" if variant else ""
    raise SystemExit(f"selection {app}{shard}: {reason}")


def check_pins(
    app: str,
    variant: str,
    offered: Sequence[str],
    *,
    pin_mode: str | None,
    pin_network: str | None,
    pin_distro: str | None,
    pin_filesystem: str | None,
    pin_architecture: str | None = None,
    pin_vpn: bool | None = None,
    states: Sequence[str],
    network_input: str,
    vpn_mode: str = "auto",
    distros: Sequence[str],
    filesystems: Sequence[str],
    architectures: Sequence[str] = ARCHITECTURES,
) -> None:
    """Prove the row can take what the selection token pinned on it.

    The offered modes are already narrowed by the run's ``--modes`` input, the
    network modes by its ``--network`` input, the mesh states by its ``--vpn``
    input and the two pools by ``--distros`` and ``--filesystem``, so this
    catches a pin that fights the role, the variant, or the run's own axes with
    one check each.
    """
    if pin_mode is not None and pin_mode not in offered:
        _reject(
            app,
            variant,
            f"pinned mode {pin_mode!r} is not available here "
            f"(offered: {', '.join(offered)})",
        )
    for value, pool, axis in (
        (pin_distro, distros, "distro"),
        (pin_filesystem, filesystems, "filesystem"),
        (pin_architecture, architectures, "architecture"),
    ):
        if value is not None and value not in pool:
            _reject(
                app,
                variant,
                f"pinned {axis} {value!r} is outside this run's {axis} pool "
                f"({', '.join(pool) or 'empty'})",
            )
    modes = (pin_mode,) if pin_mode else offered
    if pin_network is not None and not any(
        pin_network in network_states(mode, states=states, network_input=network_input)
        for mode in modes
    ):
        _reject(
            app,
            variant,
            f"pinned network mode {pin_network!r} is impossible here (mode, "
            f"variant, the role's reachability or the run's network axis "
            f"rules it out)",
        )
    if pin_vpn is not None and not any(
        pinned_vpn_states(mode, pin=pin_vpn, vpn_mode=vpn_mode) for mode in modes
    ):
        _reject(
            app,
            variant,
            f"pinned mesh state {'vpn' if pin_vpn else 'direct'} is impossible "
            f"here (only {'/'.join(VPN_DEPLOY_MODES)} meshes). A held vpn axis "
            f"overrides the pin instead and is not refused here",
        )


def row_architectures(
    app: str, run_pool: Sequence[str], services: Sequence[str] = ()
) -> tuple[str, ...]:
    """The architectures one role's rows may draw from this run.

    A role that declares none takes the run's whole pool, which is what
    spreads both architectures evenly over its variants: every row of the
    catalogue advances the same rotation, so a role's consecutive rows
    alternate rather than repeating one architecture.

    Args:
        app: role id, read for its ``meta/services.yml`` declaration.
        run_pool: what the run permits, already narrowed by its own input.
        services: the roles the row's variant deploys, each narrowing the
            row like the role's own declaration.

    Raises:
        SystemExit: the role and the run permit nothing in common. Dropping
            the row instead would report a green run for a role that never
            deployed, and picking one anyway would deploy it on hardware one
            of the two sides ruled out.
    """
    allowed = tuple(run_pool)
    declarations: list[str] = []
    for role in (app, *services):
        declared = get_role_architectures(role)
        if declared:
            declarations.append(f"{role} ({', '.join(declared)})")
            allowed = tuple(value for value in allowed if value in declared)
    if not allowed:
        raise SystemExit(
            f"{app}: meta/services.yml declares architectures for "
            f"{'; '.join(declarations)}, and this run permits "
            f"{', '.join(run_pool) or 'none'}. Widen the run's architecture "
            f"pool or the declarations."
        )
    return allowed
