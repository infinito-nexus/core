"""Prove a selection token's pins against what the row and the run permit.

Separate from :mod:`utils.github.variant.axes`, which decides the axes of a
row that carries no pin: this module only refuses the combinations a pin
asks for and the row cannot give.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.github.variant.network import combinations, network_states
from utils.github.variant.pools import ARCHITECTURES, rotate
from utils.github.variant.vpn import VPN_DEPLOY_MODES, pinned_vpn_states
from utils.packages.registry import published_architectures
from utils.packages.schema import PackagesShapeError
from utils.roles.display import VARIANT_SEPARATOR
from utils.roles.meta_lookup import get_role_architectures

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "check_pins",
    "draw_pair",
    "priority_picks",
    "row_architectures",
    "row_pairs",
]


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
    pairs: Sequence[tuple[str, str]] | None = None,
) -> None:
    """Prove the row can take what the selection token pinned on it.

    The offered modes are already narrowed by the run's ``--modes`` input, the
    network modes by its ``--network`` input, the mesh states by its ``--vpn``
    input and the two pools by ``--distros`` and ``--filesystem``, so this
    catches a pin that fights the role, the variant, or the run's own axes with
    one check each. ``pairs`` (:func:`row_pairs`) adds the distro and
    architecture combinations the row's packages are published for.
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
    if pairs is not None and not _pinned_pairs(pairs, pin_distro, pin_architecture):
        _reject(
            app,
            variant,
            f"pinned {pin_distro or 'any distro'} on "
            f"{pin_architecture or 'any architecture'} is impossible here: a "
            f"package the row installs is not published there "
            f"(meta/packages.yml architectures)",
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


def priority_picks(
    offered: Sequence[str],
    *,
    pin_mode: str | None,
    pin_network: str | None,
    pin_vpn: bool | None,
    states: Sequence[str],
    network_input: str,
    vpn_mode: str,
) -> list[tuple[str, str, bool]]:
    """Args:
        offered: the deploy modes the row offers in this run.
        pin_mode: the token's pinned deploy mode, ``None`` for any.
        pin_network: the token's pinned network mode, ``None`` for any.
        pin_vpn: the token's pinned mesh state, ``None`` for any.
        states: the network modes the row's role can be served in.
        network_input: the run's network axis.
        vpn_mode: the run's mesh axis.

    Returns:
        ``(mode, network, meshed)`` per job, empty when the row cannot deploy
        in this run at all.
    """
    return [
        (mode, state, meshed)
        for mode, state in combinations(
            offered, states=states, network_input=network_input
        )
        if pin_mode in (None, mode) and pin_network in (None, state)
        for meshed in pinned_vpn_states(mode, pin=pin_vpn, vpn_mode=vpn_mode)
    ]


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


def _pinned_pairs(
    pairs: Sequence[tuple[str, str]],
    pin_distro: str | None,
    pin_architecture: str | None,
) -> list[tuple[str, str]]:
    return [
        (distro, architecture)
        for distro, architecture in pairs
        if pin_distro in (None, distro) and pin_architecture in (None, architecture)
    ]


def row_pairs(
    app: str,
    distros: Sequence[str],
    architectures: Sequence[str],
    services: Sequence[str] = (),
) -> tuple[tuple[str, str], ...]:
    """The distro and architecture pairs one row may deploy on this run.

    Args:
        app: role id, read for the packages its ``meta/packages.yml`` installs.
        distros: the run's distro pool.
        architectures: what :func:`row_architectures` left the row.
        services: the roles the row's variant deploys, whose packages the
            deploy installs too.

    Raises:
        SystemExit: no pair is left, which dropping the row instead would
            report as a green run for a role that never deployed; or the
            registry does not parse, which planning must refuse in one line
            rather than a traceback.
    """
    try:
        published = published_architectures(PROJECT_ROOT)
    except PackagesShapeError as exc:
        raise SystemExit(f"{app}: {exc}") from exc
    pairs = tuple(
        (distro, architecture)
        for distro in distros
        for architecture in architectures
        if all(
            architecture in published.get(role, {}).get(distro, ARCHITECTURES)
            for role in (app, *services)
        )
    )
    if not pairs:
        raise SystemExit(
            f"{app}: meta/packages.yml publishes no package of the row for any "
            f"of {', '.join(distros) or 'no distro'} on "
            f"{', '.join(architectures) or 'no architecture'}. Widen the run's "
            f"distro or architecture pool."
        )
    return pairs


def draw_pair(
    pairs: Sequence[tuple[str, str]],
    distros: Sequence[str],
    architectures: Sequence[str],
    *,
    pin_distro: str | None,
    pin_architecture: str | None,
    index: int,
    sweep: int,
) -> tuple[str, str]:
    """The distro and architecture one deploy of a row takes.

    Both rotate independently. Only an unpublished draw moves: first to
    another architecture of the same distro, so the distro walk keeps its
    coprime coverage, then to another distro of the same architecture when
    the architecture is pinned.

    Args:
        pairs: :func:`row_pairs` of the row, already proven by
            :func:`check_pins` to hold a pair the pins allow.
        distros: the run's distro pool, in rotation order.
        architectures: the row's architectures, in rotation order.
        pin_distro: the token's pinned distro, ``None`` for any.
        pin_architecture: the token's pinned architecture, ``None`` for any.
        index: the deploy's rotation index.
        sweep: the sweep number.
    """
    allowed = _pinned_pairs(pairs, pin_distro, pin_architecture)
    distro = pin_distro or rotate(distros, index, sweep)
    architecture = pin_architecture or rotate(architectures, index, sweep)
    if (distro, architecture) in allowed:
        return distro, architecture
    same_distro = [pair for pair in allowed if pair[0] == distro]
    same_architecture = [pair for pair in allowed if pair[1] == architecture]
    for candidates in (
        [] if pin_architecture else same_distro,
        [] if pin_distro else same_architecture,
        allowed,
    ):
        if candidates:
            return candidates[(index + sweep) % len(candidates)]
    raise AssertionError("check_pins proved a pair the pins allow")
