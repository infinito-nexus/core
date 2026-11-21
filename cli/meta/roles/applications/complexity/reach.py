"""What a row's deploy brings up, as the deploy planner settles it."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from cli.administration.deploy.development.inventory.legacy_resolver import (
    prune_orphans_after_disable,
)
from cli.administration.inventory.provision.services.disabler import (
    find_provider_roles,
    parse_services_disabled,
)
from utils.cache.applications import get_variants
from utils.github.variant import network
from utils.github.variant.pools import MODES
from utils.roles.applications.variants import resolve_round

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from utils.roles.applications.variants import ResolvedRound

    from .model import ComplexityRow


class Rounds(NamedTuple):
    """The deploy planner's answers the coverage cut asks of a row, cheapest
    first, so the cut can stop at the first that rules a coverer out.

    Attributes:
        modes: the deploy modes the row is tested in.
        networks: the node network modes those deploy modes can take it to.
        runs: ``{role: variant it runs in}`` for every role the row's round
            deploys in each of its network modes.
    """

    modes: Callable[[ComplexityRow], frozenset[str]]
    networks: Callable[[ComplexityRow], frozenset[str]]
    runs: Callable[[ComplexityRow], Mapping[str, int]]


@functools.cache
def _round_of(roles_dir: str, app: str, variant: int) -> ResolvedRound:
    """The round of ``app#variant``, settled as the deploy planner settles it
    (``plan_dev_inventory_matrix`` resolves the same round, but every round of
    the app, which a row asking for one of fourteen does not need).

    Args:
        roles_dir: the roles tree the round is read from.
        app: the round's only primary app.
        variant: the primary's variant, which is also the round index.
    """
    return resolve_round(
        roles_dir=roles_dir,
        round_index=variant,
        primary_app_variants={app: variant},
        variants_per_app=get_variants(roles_dir=roles_dir, readonly=True),
    )


@functools.cache
def _networks(
    roles_dir: str, app: str, variant: int, modes: frozenset[str]
) -> frozenset[str]:
    """The node network modes ``app#variant`` can be deployed in.

    Args:
        roles_dir: the roles tree the round is read from.
        app: the round's only primary app.
        variant: the primary's variant, which is also the round index.
        modes: the deploy modes the row is tested in.
    """
    states = network.row_states(
        app,
        variant,
        get_variants(roles_dir=roles_dir, readonly=True),
        pulls_tor=network.tor_provider() in _round_of(roles_dir, app, variant).include,
    )
    return frozenset(
        state
        for mode in sorted(modes)
        for state in network.network_states(
            mode, states=states, network_input=network.AUTO
        )
    )


@functools.cache
def _runs(
    roles_dir: str, app: str, variant: int, networks: frozenset[str]
) -> Mapping[str, int]:
    """What ``app#variant`` deploys in every one of ``networks``.

    A network mode deploys with ``disable`` set as the matrix entry sets it
    (:func:`utils.github.variant.network.disabled_services`), and the deploy
    cuts those roles and every dependency only they pulled in
    (``prune_orphans_after_disable``).

    Args:
        roles_dir: the roles tree the round is read from.
        app: the round's only primary app.
        variant: the primary's variant, which is also the round index.
        networks: the node network modes the row can be deployed in.
    """
    resolved = _round_of(roles_dir, app, variant)
    kept = set(resolved.include)
    for state in sorted(networks):
        tokens = network.disabled_services(state, resolved.include)
        if not tokens:
            continue
        kept &= set(
            prune_orphans_after_disable(
                include=resolved.include,
                primary_apps=[app],
                disabled_app_ids=set(
                    find_provider_roles(
                        parse_services_disabled(tokens), Path(roles_dir)
                    ).values()
                ),
                services_overrides=resolved.services_overrides,
            )[0]
        )
    running = {**resolved.active_index, app: variant}
    return {role: running.get(role, 0) for role in resolved.include if role in kept}


def rounds(roles_dir: Path) -> Rounds:
    """The planner's answers for the coverage cut, read from ``roles_dir``.

    Args:
        roles_dir: the roles tree the rounds are read from.

    Returns:
        :class:`Rounds` over that tree; a whole-role row is round 0.
    """
    root = str(roles_dir)

    def modes(row: ComplexityRow) -> frozenset[str]:
        return frozenset(mode for mode in MODES if getattr(row, f"test_{mode}"))

    def networks(row: ComplexityRow) -> frozenset[str]:
        return _networks(root, row.name, row.variant or 0, modes(row))

    def runs(row: ComplexityRow) -> Mapping[str, int]:
        return _runs(root, row.name, row.variant or 0, networks(row))

    return Rounds(modes, networks, runs)
