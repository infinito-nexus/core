"""Integration: a row the sweep cuts as covered is deployed by its coverer.

The cut drops a ``role#0`` row because an earlier row already brings that role
up in variant 0. When the claim is wrong, no job of the sweep deploys the row
and the plan still reads as complete. The complexity closure over-approximates
a round (it walks every provider's base ``meta/services.yml``), so the claim is
checked here against what the deploy jobs themselves run: the planner's include
pruned by ``disable`` as the compose and host deploy prunes it, and the include
a swarm job derives (``utils.tests.swarm.derive_includes``). The deploy and
network axes are assigned after the cut, so the claim must hold in every deploy
mode and network mode the coverer can rotate to.
"""

from __future__ import annotations

import functools
import os
import unittest
from unittest import mock

from cli.administration.deploy.development.inventory import (
    _build_services_overrides_for_round as build_services_overrides_for_round,
)
from cli.administration.deploy.development.inventory import (
    plan_dev_inventory_matrix,
    prune_orphans_after_disable,
)
from cli.administration.inventory.provision.services.disabler import (
    find_provider_roles,
    parse_services_disabled,
)
from cli.meta.ci import query
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT
from utils.github.variant import network
from utils.github.variant.pools import MODES
from utils.tests.swarm.derive_includes import derive_includes

ROLES = PROJECT_ROOT / "roles"


@functools.cache
def _rounds(app: str) -> tuple[tuple[dict[str, int], tuple[str, ...]], ...]:
    return tuple(
        (dict(variants), tuple(include))
        for _index, _dir, variants, include, _purge in plan_dev_inventory_matrix(
            roles_dir=str(ROLES),
            primary_apps=[app],
            base_inventory_dir="plan",
        )
    )


@functools.cache
def _rows() -> tuple[dict, ...]:
    return tuple(query.discover_rows(query.resolve_modes(query.ALL_MODES)))


@functools.cache
def _covered() -> tuple[tuple[dict, dict], ...]:
    by_id = {row["id"]: row for row in _rows()}
    return tuple(
        (row, by_id[row["covered_by"]]) for row in _rows() if row["covered_by"] in by_id
    )


def _row(name: str, variant: int) -> dict:
    return next(
        row for row in _rows() if (row["name"], row["variant"] or 0) == (name, variant)
    )


def _modes(row: dict) -> set[str]:
    return {mode for mode in MODES if row.get(f"test_{mode}")}


def _networks_by_mode(row: dict) -> dict[str, tuple[str, ...]]:
    """The node network modes each deploy mode of ``row`` can take it to.

    Args:
        row: a discovered row.

    Returns:
        ``{deploy mode: network modes}`` for every mode ``row`` is tested in.
    """
    include = _rounds(row["name"])[row["variant"] or 0][1]
    states = network.row_states(
        row["name"],
        row["variant"],
        get_variants(roles_dir=str(ROLES), readonly=True),
        pulls_tor=network.tor_provider() in include,
    )
    return {
        mode: tuple(
            network.network_states(mode, states=states, network_input=network.AUTO)
        )
        for mode in sorted(_modes(row))
    }


def _network_losses(row: dict, coverer: dict) -> list[str]:
    """Every ``mode/network`` the sweep can give ``row`` but never ``coverer``.

    Args:
        row: the cut row.
        coverer: the row it is cut for.
    """
    offered = _networks_by_mode(coverer)
    return [
        f"{mode}/{state}"
        for mode, states in _networks_by_mode(row).items()
        for state in states
        if state not in offered.get(mode, ())
    ]


@functools.cache
def _deployed(app: str, index: int, mode: str, tokens: str) -> frozenset[str]:
    """The roles a ``mode`` job of ``app#index`` deploys under ``disable``.

    Args:
        app: the job's primary role.
        index: the job's round index.
        mode: the job's deploy mode.
        tokens: the job's ``disable`` value.
    """
    variants, include = _rounds(app)[index]
    if mode == "swarm":
        with mock.patch.dict(os.environ, {"disable": tokens}):
            return frozenset(derive_includes(app, variants=variants))
    if not tokens:
        return frozenset(include)
    disabled = set(find_provider_roles(parse_services_disabled(tokens), ROLES).values())
    return frozenset(
        prune_orphans_after_disable(
            include=include,
            primary_apps=[app] if app not in disabled else [],
            disabled_app_ids=disabled,
            services_overrides=build_services_overrides_for_round(
                roles_dir=str(ROLES),
                round_index=index,
                primary_app_variants={app: variants.get(app, index)},
            ),
        )[0]
    )


def _losses(row: dict, coverer: dict) -> list[str]:
    """Every deploy mode and network mode of ``coverer`` whose job leaves
    ``row`` out.

    Args:
        row: the cut row.
        coverer: the row it is cut for.

    Returns:
        ``mode/network disable=...`` per such job.
    """
    index = coverer["variant"] or 0
    include = _rounds(coverer["name"])[index][1]
    return [
        f"{mode}/{state} disable={tokens!r}"
        for mode, states in _networks_by_mode(coverer).items()
        for state in states
        for tokens in (network.disabled_services(state, include),)
        if row["name"] not in _deployed(coverer["name"], index, mode, tokens)
    ]


class TestCoveredRowsAreDeployed(unittest.TestCase):
    def test_every_cut_row_runs_in_variant_zero_in_its_coverers_round(self) -> None:
        findings = [
            f"  - {query.token(row)} cut for {query.token(coverer)}, whose round "
            f"runs it as {variants.get(row['name'], 0) if row['name'] in include else 'nothing'!r}"
            for row, coverer in _covered()
            for variants, include in (
                _rounds(coverer["name"])[coverer["variant"] or 0],
            )
            if row["name"] not in include or variants.get(row["name"], 0) != 0
        ]
        self.assertFalse(
            findings,
            f"{len(findings)} row(s) are cut as covered by a row whose deploy "
            "never brings them up in variant 0, so no job deploys them:\n"
            + "\n".join(findings),
        )

    def test_every_job_the_coverer_can_get_deploys_the_cut_row(self) -> None:
        findings = [
            f"  - {query.token(row)} cut for {query.token(coverer)}, whose "
            f"{loss} job leaves it out"
            for row, coverer in _covered()
            for loss in _losses(row, coverer)
        ]
        self.assertFalse(
            findings,
            f"{len(findings)} cut row(s) are left out of a job their coverer can "
            "rotate to, so that sweep deploys them nowhere:\n" + "\n".join(findings),
        )

    def test_every_cut_row_is_tested_only_in_modes_its_coverer_is_tested_in(
        self,
    ) -> None:
        findings = [
            f"  - {query.token(row)} cut for {query.token(coverer)}, which is "
            f"never deployed in {sorted(_modes(row) - _modes(coverer))}"
            for row, coverer in _covered()
            if not _modes(row) <= _modes(coverer)
        ]
        self.assertFalse(
            findings,
            f"{len(findings)} cut row(s) offer a deploy mode their coverer does "
            "not, so no job deploys them in it:\n" + "\n".join(findings),
        )

    def test_every_network_mode_of_a_cut_row_is_one_its_coverer_takes(
        self,
    ) -> None:
        findings = [
            f"  - {query.token(row)} cut for {query.token(coverer)}, which never "
            f"deploys in {loss}"
            for row, coverer in _covered()
            for loss in _network_losses(row, coverer)
        ]
        self.assertFalse(
            findings,
            f"{len(findings)} cut row(s) can be given a network mode their coverer "
            "never is, so no job deploys them in it:\n" + "\n".join(findings),
        )

    def test_the_network_guard_reports_a_network_the_coverer_never_takes(
        self,
    ) -> None:
        self.assertIn(
            "swarm/multi",
            _network_losses(
                _row("svc-ai-libretranslate-engine", 0), _row("web-svc-translate", 4)
            ),
        )

    def test_the_guard_reports_a_disable_that_drops_the_cut_row(self) -> None:
        row, coverer = next(
            (row, coverer)
            for row, coverer in _covered()
            if _modes(coverer) & {"compose", "host"}
        )
        with mock.patch.object(
            network, "disabled_services", lambda state, include: row["name"]
        ):
            self.assertTrue(_losses(row, coverer))

    def test_the_scan_finds_cut_rows_to_judge(self) -> None:
        self.assertTrue(
            _covered(), "no discovered row is cut as covered; the check is vacuous"
        )


if __name__ == "__main__":
    unittest.main()
