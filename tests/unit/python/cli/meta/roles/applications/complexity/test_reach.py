"""The coverage cut's view of a round: the networks a row takes and the roles
its round still runs once each network's ``disable`` is applied."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cli.meta.roles.applications.complexity import reach

APP = "web-app-a"
ROUND = SimpleNamespace(
    include=("svc-db", "svc-net-tor", "web-svc-partner", APP),
    active_index={"svc-db": 2},
    services_overrides={},
)
DISABLE = {"clearnet": "tor", "tor": "web-svc-partner", "multi": ""}
PROVIDERS = {"tor": "svc-net-tor", "web-svc-partner": "web-svc-partner"}
ORPHANS = {
    "svc-net-tor": {"svc-net-tor"},
    "web-svc-partner": {"web-svc-partner", "svc-db"},
}
STATES = {"compose": ("clearnet",), "swarm": ("tor", "multi"), "host": ("clearnet",)}


def _prune(
    *,
    include: tuple[str, ...],
    primary_apps: list[str],
    disabled_app_ids: set[str],
    services_overrides: dict,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A ``prune_orphans_after_disable`` stub cutting each disabled role with
    the dependencies listed for it in ``ORPHANS``.

    Args:
        include: the round's include.
        primary_apps: the round's primaries, unused.
        disabled_app_ids: the roles ``disable`` cuts.
        services_overrides: the round's service maps, unused.

    Returns:
        ``(kept, pruned)`` in include order.
    """
    gone = set().union(*(ORPHANS[role] for role in disabled_app_ids))
    return tuple(r for r in include if r not in gone), tuple(
        r for r in include if r in gone
    )


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        caches = (reach._round_of, reach._networks, reach._runs)
        for fn in caches:
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        self.row_states = mock.Mock(return_value=("clearnet", "tor", "multi"))
        for patch in (
            mock.patch.object(reach, "_round_of", return_value=ROUND),
            mock.patch.object(reach, "get_variants", return_value={}),
            mock.patch.object(reach.network, "row_states", self.row_states),
            mock.patch.object(
                reach.network, "tor_provider", return_value="svc-net-tor"
            ),
            mock.patch.object(
                reach.network,
                "network_states",
                side_effect=lambda mode, states, network_input: STATES[mode],
            ),
            mock.patch.object(
                reach.network,
                "disabled_services",
                side_effect=lambda state, include: DISABLE[state],
            ),
            mock.patch.object(
                reach,
                "find_provider_roles",
                side_effect=lambda services, roles_dir: {
                    s: PROVIDERS[s] for s in services
                },
            ),
            mock.patch.object(reach, "prune_orphans_after_disable", side_effect=_prune),
        ):
            patch.start()
            self.addCleanup(patch.stop)


class TestRuns(_Fixture):
    def test_a_network_without_disable_runs_the_whole_round(self) -> None:
        self.assertEqual(
            reach._runs("roles", APP, 3, frozenset({"multi"})),
            {"svc-db": 2, "svc-net-tor": 0, "web-svc-partner": 0, APP: 3},
        )

    def test_a_network_cuts_its_disabled_role_and_the_orphans_it_leaves(
        self,
    ) -> None:
        self.assertEqual(
            reach._runs("roles", APP, 3, frozenset({"tor"})),
            {"svc-net-tor": 0, APP: 3},
        )

    def test_a_role_any_network_cuts_is_not_run(self) -> None:
        self.assertEqual(
            reach._runs("roles", APP, 3, frozenset({"clearnet", "tor"})), {APP: 3}
        )


class TestNetworks(_Fixture):
    def test_the_networks_are_those_of_every_tested_mode(self) -> None:
        self.assertEqual(
            reach._networks("roles", APP, 0, frozenset({"compose", "swarm"})),
            {"clearnet", "tor", "multi"},
        )

    def test_a_row_tested_in_no_mode_takes_no_network(self) -> None:
        self.assertEqual(reach._networks("roles", APP, 0, frozenset()), frozenset())

    def test_the_round_decides_whether_the_row_pulls_tor(self) -> None:
        reach._networks("roles", APP, 0, frozenset({"compose"}))
        self.assertTrue(self.row_states.call_args.kwargs["pulls_tor"])


class TestRounds(_Fixture):
    def test_the_modes_are_the_tested_ones(self) -> None:
        row = SimpleNamespace(
            name=APP, variant=None, test_compose=True, test_swarm=False, test_host=True
        )
        self.assertEqual(reach.rounds("roles").modes(row), {"compose", "host"})

    def test_a_whole_role_row_runs_round_zero(self) -> None:
        row = SimpleNamespace(
            name=APP, variant=None, test_compose=True, test_swarm=False, test_host=False
        )
        self.assertEqual(reach.rounds("roles").runs(row)[APP], 0)


if __name__ == "__main__":
    unittest.main()
