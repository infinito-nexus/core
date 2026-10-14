from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.github.variant import axes, network, pools
from utils.roles.display import display_names
from utils.symbol_glossary import to_emoji

_REACTIVE = "{{ 'svc-net-tor' in group_names }}"

_VARIANTS = {
    "web-app-a": [
        {"services": {"tor": {"enabled": True}}},
        {"services": {"tor": {"enabled": False}}},
    ],
    "web-app-b": [{"services": {"tor": {"enabled": _REACTIVE}}}],
    "web-app-c": [{"services": {}}],
    "web-app-single": [
        {
            "services": {"tor": {"enabled": _REACTIVE}},
            "networks": {"reachability": {"single_mode": True}},
        }
    ],
    "web-app-clear": [
        {
            "services": {"tor": {"enabled": _REACTIVE}},
            "networks": {"reachability": {"modes": ["clearnet"]}},
        }
    ],
    "web-app-dark": [
        {
            "services": {"tor": {"enabled": _REACTIVE}},
            "networks": {"reachability": {"modes": ["tor"]}},
        }
    ],
}

_ALL = ("clearnet", "tor", "multi")


def _row(name: str, variant: int, modes: tuple[str, ...], **extra) -> dict:
    return {"name": name, "variant": variant, "modes": modes, **extra}


def _assign(rows, **kwargs) -> list[dict[str, str]]:
    """:func:`axes.assign` on the full declared pools, which is what an
    unnarrowed run hands it."""
    kwargs.setdefault("distros", axes.DISTROS)
    kwargs.setdefault("filesystems", axes.FILESYSTEMS)
    return axes.assign(rows, **kwargs)


class TestResolveNetworkInput(unittest.TestCase):
    def test_known_inputs_pass_through(self) -> None:
        for value in network.NETWORK_INPUTS:
            self.assertEqual(network.resolve_network_input(value), value)

    def test_unknown_and_empty_fall_back_to_auto(self) -> None:
        self.assertEqual(network.resolve_network_input("nonsense"), "auto")
        self.assertEqual(network.resolve_network_input(""), "auto")

    def test_the_retired_tor_axis_values_are_not_network_modes(self) -> None:
        for value in ("enforced", "exclusive", "disabled"):
            self.assertEqual(network.resolve_network_input(value), "auto")


class TestResolveSweep(unittest.TestCase):
    def test_a_number_is_read(self) -> None:
        self.assertEqual(axes.resolve_sweep("7"), 7)

    def test_garbage_reads_as_zero(self) -> None:
        self.assertEqual(axes.resolve_sweep("x"), 0)
        self.assertEqual(axes.resolve_sweep(""), 0)


class TestRowStates(unittest.TestCase):
    def test_a_capable_row_takes_every_network_mode(self) -> None:
        self.assertEqual(network.row_states("web-app-b", 0, _VARIANTS), _ALL)
        self.assertEqual(network.row_states("web-app-a", 0, _VARIANTS), _ALL)

    def test_a_role_without_a_bond_takes_multi_when_its_deploy_pulls_tor(self) -> None:
        self.assertEqual(
            network.row_states("web-app-c", 0, _VARIANTS, pulls_tor=True),
            ("clearnet", "multi"),
        )

    def test_a_gate_pinned_false_ignores_a_pulled_in_provider(self) -> None:
        self.assertEqual(
            network.row_states("web-app-a", 1, _VARIANTS, pulls_tor=True),
            ("clearnet",),
        )

    def test_the_services_closure_decides_whether_tor_is_pulled_in(self) -> None:
        provider = network.tor_provider()
        self.assertTrue(network.row_pulls_tor({"services": ["svc-db-x", provider]}))
        self.assertFalse(network.row_pulls_tor({"services": ["svc-db-x"]}))
        self.assertFalse(network.row_pulls_tor({}))

    def test_an_incapable_row_only_takes_clearnet(self) -> None:
        self.assertEqual(network.row_states("web-app-a", 1, _VARIANTS), ("clearnet",))
        self.assertEqual(network.row_states("web-app-c", 0, _VARIANTS), ("clearnet",))

    def test_a_single_mode_role_never_takes_multi(self) -> None:
        self.assertEqual(
            network.row_states("web-app-single", 0, _VARIANTS), ("clearnet", "tor")
        )

    def test_restricted_modes_narrow_the_node_modes(self) -> None:
        self.assertEqual(
            network.row_states("web-app-clear", 0, _VARIANTS), ("clearnet",)
        )
        self.assertEqual(network.row_states("web-app-dark", 0, _VARIANTS), ("tor",))

    def test_the_provider_never_takes_clearnet(self) -> None:
        provider = network.tor_provider()
        self.assertIsNotNone(provider)
        self.assertEqual(network.row_states(provider), ("tor", "multi"))


class TestPickMode(unittest.TestCase):
    def test_a_single_offer_is_always_taken(self) -> None:
        for position in range(4):
            self.assertEqual(axes.pick_mode(("host",), position, 0), "host")

    def test_two_offers_alternate_by_position(self) -> None:
        offered = ("compose", "swarm")
        picks = [axes.pick_mode(offered, position, 0) for position in range(4)]
        self.assertEqual(picks, ["compose", "swarm", "compose", "swarm"])

    def test_the_sweep_flips_which_offer_leads(self) -> None:
        offered = ("compose", "swarm")
        self.assertEqual(axes.pick_mode(offered, 0, 0), "compose")
        self.assertEqual(axes.pick_mode(offered, 0, 1), "swarm")

    def test_an_empty_offer_is_a_bug_not_a_fallback(self) -> None:
        with self.assertRaises(ValueError):
            axes.pick_mode((), 0, 0)


class TestAxesDecouple(unittest.TestCase):
    def test_a_row_walks_all_six_combinations_in_six_sweeps(self) -> None:
        row = _row("web-app-b", 0, ("compose", "swarm"))
        seen = {
            (entry["mode"], entry["network"])
            for sweep in range(6)
            for entry in _assign(
                [row], sweep=sweep, network_input="auto", variants_per_app=_VARIANTS
            )
        }
        self.assertEqual(len(seen), 6)

    def test_a_two_state_row_walks_all_four_combinations_in_four_sweeps(self) -> None:
        row = _row("web-app-single", 0, ("compose", "swarm"))
        seen = {
            (entry["mode"], entry["network"])
            for sweep in range(4)
            for entry in _assign(
                [row], sweep=sweep, network_input="auto", variants_per_app=_VARIANTS
            )
        }
        self.assertEqual(len(seen), 4)


class TestGlyphBinding(unittest.TestCase):
    def test_the_local_glyph_is_the_house_symbol(self) -> None:
        self.assertEqual("🏠", axes.LOCAL_GLYPH)

    def test_the_multi_mode_wears_the_rainbow(self) -> None:
        self.assertEqual("🌈", to_emoji("multi"))


class TestArtifactSlug(unittest.TestCase):
    def test_the_entry_carries_the_slug_the_reporter_looks_for(self) -> None:
        from cli.meta.ci.report_failures import Failure, artifact_name

        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        for entry in entries:
            with self.subTest(entry["label"]):
                self.assertEqual(
                    f"rescue-diagnostics-{entry['artifact']}",
                    artifact_name(
                        entry["apps"],
                        Failure(
                            entry["mode"],
                            entry["variant"],
                            entry["network"],
                            entry["distro"],
                            entry["filesystem"],
                        ),
                    ),
                )

    def test_the_network_mode_keeps_runs_of_one_variant_apart(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(len({e["artifact"] for e in entries}), len(entries))

    def test_a_variantless_row_gets_no_dangling_separator(self) -> None:
        self.assertEqual(
            axes.artifact_slug("host", "sys-front-proxy", "", "clearnet"),
            "host-sys-front-proxy",
        )

    def test_only_a_network_beyond_clearnet_adds_a_shard(self) -> None:
        self.assertEqual(
            axes.artifact_slug("compose", "web-app-b", "0", "multi"),
            "compose-web-app-b-0-multi",
        )
        self.assertEqual(
            axes.artifact_slug("compose", "web-app-b", "0", "tor"),
            "compose-web-app-b-0-tor",
        )


class TestNetworkStates(unittest.TestCase):
    def test_a_capable_row_covers_every_mode_under_auto(self) -> None:
        self.assertEqual(
            network.network_states("compose", states=_ALL, network_input="auto"),
            list(_ALL),
        )

    def test_an_incapable_row_only_runs_clearnet(self) -> None:
        self.assertEqual(
            network.network_states(
                "compose", states=("clearnet",), network_input="auto"
            ),
            ["clearnet"],
        )

    def test_host_carries_no_network_axis(self) -> None:
        self.assertEqual(
            network.network_states("host", states=_ALL, network_input="auto"),
            ["clearnet"],
        )

    def test_a_named_input_narrows_to_that_mode(self) -> None:
        for value in _ALL:
            with self.subTest(value):
                self.assertEqual(
                    network.network_states("compose", states=_ALL, network_input=value),
                    [value],
                )

    def test_a_named_input_the_row_cannot_take_drops_it(self) -> None:
        self.assertEqual(
            network.network_states(
                "compose", states=("clearnet",), network_input="multi"
            ),
            [],
        )

    def test_only_clearnet_disables_the_tor_provider(self) -> None:
        self.assertEqual(network.disabled_services("clearnet"), "tor")
        self.assertEqual(network.disabled_services("tor"), "")
        self.assertEqual(network.disabled_services("multi"), "")


class TestCombinations(unittest.TestCase):
    def test_two_modes_on_the_network_axis_yield_six_runs(self) -> None:
        self.assertEqual(
            network.combinations(
                ("compose", "swarm"), states=_ALL, network_input="auto"
            ),
            [
                ("compose", "clearnet"),
                ("compose", "tor"),
                ("compose", "multi"),
                ("swarm", "clearnet"),
                ("swarm", "tor"),
                ("swarm", "multi"),
            ],
        )

    def test_a_stackless_role_yields_compose_triple_plus_one_host(self) -> None:
        self.assertEqual(
            network.combinations(
                ("compose", "host"), states=_ALL, network_input="auto"
            ),
            [
                ("compose", "clearnet"),
                ("compose", "tor"),
                ("compose", "multi"),
                ("host", "clearnet"),
            ],
        )

    def test_an_incapable_variant_keeps_one_run_per_mode(self) -> None:
        self.assertEqual(
            network.combinations(
                ("compose", "swarm"), states=("clearnet",), network_input="auto"
            ),
            [("compose", "clearnet"), ("swarm", "clearnet")],
        )


class TestPriorityCoverage(unittest.TestCase):
    def test_a_priority_row_runs_every_combination_in_one_sweep(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(
            {(e["mode"], e["network"]) for e in entries},
            {(mode, state) for mode in ("compose", "swarm") for state in _ALL},
        )

    def test_a_regular_row_still_takes_exactly_one_combination(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"))]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(len(entries), 1)

    def test_priority_coverage_does_not_move_with_the_sweep(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        shapes = {
            frozenset(
                (e["mode"], e["network"])
                for e in _assign(
                    rows, sweep=sweep, network_input="auto", variants_per_app=_VARIANTS
                )
            )
            for sweep in range(4)
        }
        self.assertEqual(len(shapes), 1)

    def test_every_priority_job_gets_a_distinct_label(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(len({e["label"] for e in entries}), len(entries))

    def test_an_incapable_priority_variant_skips_its_tor_runs(self) -> None:
        rows = [_row("web-app-a", 1, ("compose", "swarm"), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["network"] for e in entries], ["clearnet", "clearnet"])

    def test_a_single_mode_priority_row_never_runs_multi(self) -> None:
        rows = [_row("web-app-single", 0, ("compose",), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["network"] for e in entries], ["clearnet", "tor"])


class TestAssign(unittest.TestCase):
    def test_every_row_becomes_one_entry(self) -> None:
        rows = [
            _row("web-app-a", 0, ("compose", "swarm")),
            _row("web-app-a", 1, ("compose", "swarm")),
        ]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["variant"] for e in entries], ["0", "1"])

    def test_the_label_opens_with_the_mode_glyph(self) -> None:
        rows = [_row("web-app-a", 0, ("compose",))]
        entry = _assign(
            rows, sweep=0, network_input="clearnet", variants_per_app=_VARIANTS
        )[0]
        self.assertTrue(entry["label"].startswith(to_emoji("compose")))

    def test_a_host_row_carries_no_network_glyph(self) -> None:
        rows = [_row("web-app-b", 0, ("host",))]
        entry = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )[0]
        self.assertEqual(entry["network"], "clearnet")
        for state in _ALL:
            self.assertNotIn(to_emoji(state), entry["label"])

    def test_a_priority_row_wears_the_star(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entry = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )[0]
        self.assertTrue(entry["label"].endswith(to_emoji("priority")))
        self.assertEqual(entry["priority"], "true")

    def test_a_named_input_keeps_only_the_rows_that_can_take_it(self) -> None:
        rows = [
            _row("web-app-a", 0, ("compose",)),
            _row("web-app-a", 1, ("compose",)),
        ]
        entries = _assign(
            rows, sweep=0, network_input="tor", variants_per_app=_VARIANTS
        )
        self.assertEqual(
            [(e["variant"], e["network"]) for e in entries], [("0", "tor")]
        )

    def test_a_named_input_never_rotates_a_row_onto_a_mode_that_cannot_take_it(
        self,
    ) -> None:
        row = _row("web-app-b", 0, ("compose", "host"))
        for sweep in range(4):
            with self.subTest(sweep=sweep):
                entries = _assign(
                    [row], sweep=sweep, network_input="tor", variants_per_app=_VARIANTS
                )
                self.assertEqual(
                    [(e["mode"], e["network"]) for e in entries], [("compose", "tor")]
                )

    def test_a_row_no_mode_can_serve_under_the_input_is_dropped(self) -> None:
        rows = [_row("web-app-a", 1, ("compose", "host"))]
        self.assertEqual(
            _assign(rows, sweep=0, network_input="multi", variants_per_app=_VARIANTS),
            [],
        )

    def test_a_row_without_a_bond_rides_the_multi_node_its_deploy_pulls_tor_into(
        self,
    ) -> None:
        provider = network.tor_provider()
        pulling = [_row("web-app-c", 0, ("compose",), services=[provider])]
        entries = _assign(
            pulling, sweep=0, network_input="multi", variants_per_app=_VARIANTS
        )
        self.assertEqual(
            [(e["network"], e["disable"]) for e in entries], [("multi", "")]
        )
        plain = [_row("web-app-c", 0, ("compose",))]
        self.assertEqual(
            _assign(plain, sweep=0, network_input="multi", variants_per_app=_VARIANTS),
            [],
        )

    def test_the_clearnet_input_serves_every_row_without_tor(self) -> None:
        rows = [_row("web-app-a", 0, ("compose",)), _row("web-app-a", 1, ("compose",))]
        entries = _assign(
            rows, sweep=0, network_input="clearnet", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["network"] for e in entries], ["clearnet", "clearnet"])
        self.assertEqual([e["disable"] for e in entries], ["tor", "tor"])

    def test_a_row_without_tor_disables_the_provider(self) -> None:
        rows = [_row("web-app-a", 1, ("compose",))]
        entry = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )[0]
        self.assertEqual(entry["disable"], "tor")

    def test_tor_and_multi_rows_keep_the_provider(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(
            {e["network"]: e["disable"] for e in entries},
            {"clearnet": "tor", "tor": "", "multi": ""},
        )

    def test_a_host_row_carries_the_local_glyph_where_network_rows_carry_theirs(
        self,
    ) -> None:
        entries = _assign(
            [
                _row("web-app-a", 0, ("host",)),
                _row("web-app-a", 0, ("compose",), pin_network="tor"),
            ],
            sweep=0,
            network_input="auto",
            variants_per_app=_VARIANTS,
        )
        host, compose = entries
        self.assertTrue(host["label"].startswith(to_emoji("host") + axes.LOCAL_GLYPH))
        self.assertTrue(
            compose["label"].startswith(to_emoji("compose") + to_emoji("tor"))
        )
        self.assertEqual(axes.parse_label(host["label"]).mode, "host")

    def test_the_provider_row_never_takes_the_clearnet_state(self) -> None:
        provider = network.tor_provider()
        self.assertIsNotNone(provider)
        for sweep in range(4):
            for value in network.NETWORK_INPUTS:
                with self.subTest(sweep=sweep, network_input=value):
                    entries = _assign(
                        [_row(provider, 0, ("compose", "swarm"), priority=True)],
                        sweep=sweep,
                        network_input=value,
                    )
                    self.assertEqual(
                        [e["disable"] for e in entries], [""] * len(entries)
                    )
                    self.assertNotIn("clearnet", [e["network"] for e in entries])


class TestPinnedAxes(unittest.TestCase):
    def _entries(self, row: dict) -> list[dict[str, str]]:
        return _assign([row], sweep=0, network_input="auto", variants_per_app=_VARIANTS)

    def test_a_pinned_mode_replaces_the_rotation(self) -> None:
        row = _row("web-app-b", 0, ("compose", "swarm"), pin_mode="swarm")
        self.assertEqual([e["mode"] for e in self._entries(row)], ["swarm"])

    def test_a_pinned_network_mode_replaces_the_rotation(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_network="multi")
        self.assertEqual([e["network"] for e in self._entries(row)], ["multi"])

    def test_an_open_axis_still_rotates(self) -> None:
        row = _row("web-app-b", 0, ("compose", "swarm"), pin_network="clearnet")
        picks = {
            _assign(
                [row], sweep=sweep, network_input="auto", variants_per_app=_VARIANTS
            )[0]["mode"]
            for sweep in range(2)
        }
        self.assertEqual(picks, {"compose", "swarm"})

    def test_pinning_tor_keeps_the_rotation_off_host(self) -> None:
        row = _row("web-app-b", 0, ("compose", "host"), pin_network="tor")
        for sweep in range(4):
            with self.subTest(sweep=sweep):
                entries = _assign(
                    [row], sweep=sweep, network_input="auto", variants_per_app=_VARIANTS
                )
                self.assertEqual([e["mode"] for e in entries], ["compose"])

    def test_a_pin_narrows_the_priority_cross_product(self) -> None:
        row = _row(
            "web-app-b", 0, ("compose", "swarm"), priority=True, pin_mode="compose"
        )
        entries = self._entries(row)
        self.assertEqual(
            {(e["mode"], e["network"]) for e in entries},
            {("compose", state) for state in _ALL},
        )

    def test_a_fully_pinned_priority_row_runs_exactly_once(self) -> None:
        row = _row(
            "web-app-b",
            0,
            ("compose", "swarm"),
            priority=True,
            pin_mode="swarm",
            pin_network="clearnet",
        )
        self.assertEqual(len(self._entries(row)), 1)

    def test_an_unoffered_mode_aborts_the_matrix(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_mode="swarm")
        with self.assertRaises(SystemExit):
            self._entries(row)

    def test_an_impossible_network_mode_aborts_the_matrix(self) -> None:
        row = _row("web-app-a", 1, ("compose",), pin_network="tor")
        with self.assertRaises(SystemExit):
            self._entries(row)

    def test_multi_on_a_single_mode_role_aborts_the_matrix(self) -> None:
        row = _row("web-app-single", 0, ("compose",), pin_network="multi")
        with self.assertRaises(SystemExit):
            self._entries(row)

    def test_a_pin_fighting_the_runs_network_axis_aborts(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_network="tor")
        with self.assertRaises(SystemExit):
            _assign(
                [row], sweep=0, network_input="clearnet", variants_per_app=_VARIANTS
            )


class TestResolvePool(unittest.TestCase):
    def test_an_empty_input_opens_the_whole_declared_set(self) -> None:
        self.assertEqual(
            pools.resolve_pool("", axes.DISTROS, "distro"), tuple(axes.DISTROS)
        )
        self.assertEqual(
            pools.resolve_pool(None, axes.FILESYSTEMS, "filesystem"), axes.FILESYSTEMS
        )

    def test_a_named_subset_keeps_the_declaration_order(self) -> None:
        self.assertEqual(
            pools.resolve_pool("ext4 zfs", axes.FILESYSTEMS, "filesystem"),
            ("zfs", "ext4"),
        )

    def test_a_typo_aborts_instead_of_narrowing_to_nothing(self) -> None:
        with self.assertRaises(SystemExit):
            pools.resolve_pool("debain", axes.DISTROS, "distro")


class TestDistroAndFilesystemAxes(unittest.TestCase):
    def _rows(self, count: int) -> list[dict]:
        return [_row("web-app-b", 0, ("compose",)) for _ in range(count)]

    def test_consecutive_rows_spread_over_the_pool(self) -> None:
        entries = _assign(
            self._rows(len(axes.DISTROS)),
            sweep=0,
            network_input="auto",
            variants_per_app=_VARIANTS,
        )
        self.assertEqual([e["distro"] for e in entries], list(axes.DISTROS))

    def test_the_sweep_moves_every_row_on_to_the_next_distro(self) -> None:
        picks = [
            _assign(
                self._rows(1),
                sweep=sweep,
                network_input="auto",
                variants_per_app=_VARIANTS,
            )[0]["distro"]
            for sweep in range(len(axes.DISTROS))
        ]
        self.assertEqual(set(picks), set(axes.DISTROS))

    def test_a_narrowed_pool_is_the_only_thing_drawn_from(self) -> None:
        entries = _assign(
            self._rows(4),
            sweep=0,
            network_input="auto",
            distros=("debian",),
            filesystems=("btrfs",),
            variants_per_app=_VARIANTS,
        )
        self.assertEqual({e["distro"] for e in entries}, {"debian"})
        self.assertEqual({e["filesystem"] for e in entries}, {"btrfs"})

    def test_a_priority_row_spreads_its_combinations_over_the_pool(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(
            len({e["distro"] for e in entries}),
            min(len(entries), len(axes.DISTROS)),
        )

    def test_a_pinned_distro_replaces_the_rotation(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), pin_distro="fedora")]
        entries = _assign(
            rows, sweep=3, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(entries[0]["distro"], "fedora")

    def test_a_pinned_filesystem_replaces_the_rotation(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), pin_filesystem="ext4")]
        entries = _assign(
            rows, sweep=1, network_input="auto", variants_per_app=_VARIANTS
        )
        self.assertEqual(entries[0]["filesystem"], "ext4")

    def test_collapsing_two_tokens_keeps_the_stronger_filesystem_claim(self) -> None:
        """The token that named the kind may be the one collapsing into a token
        that did not; losing its demand would let the deploy fall back to a
        filesystem the operator named against."""
        rows = [
            _row("web-app-b", 0, ("compose",), pin_distro="debian"),
            _row("web-app-b", 0, ("compose",), pin_filesystem="zfs"),
        ]
        entries = _assign(
            rows,
            sweep=0,
            network_input="clearnet",
            distros=("debian",),
            filesystems=("zfs",),
            variants_per_app=_VARIANTS,
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["enforce_filesystem"], "true")

    def test_a_pin_outside_the_runs_pool_aborts_the_matrix(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), pin_distro="arch")]
        with self.assertRaises(SystemExit):
            _assign(
                rows,
                sweep=0,
                network_input="auto",
                distros=("debian",),
                variants_per_app=_VARIANTS,
            )

    def test_the_glyphs_follow_the_network_slot_in_the_label(self) -> None:
        entry = _assign(
            [_row("web-app-b", 0, ("compose",))],
            sweep=0,
            network_input="clearnet",
            distros=("debian",),
            filesystems=("zfs",),
            variants_per_app=_VARIANTS,
        )[0]
        self.assertTrue(
            entry["label"].startswith(
                to_emoji("compose")
                + to_emoji("clearnet")
                + to_emoji("debian")
                + to_emoji("zfs")
            )
        )


class TestSortKey(unittest.TestCase):
    def _entries(self) -> list[dict[str, str]]:
        rows = [
            _row("web-app-b", 0, ("swarm",)),
            _row("web-app-a", 1, ("compose",)),
            _row("web-app-a", 0, ("compose",)),
        ]
        return _assign(rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS)

    def test_rows_sort_by_name_then_variant(self) -> None:
        ordered = sorted(self._entries(), key=axes.sort_key)
        self.assertEqual(
            [(e["apps"], e["variant"]) for e in ordered],
            [("web-app-a", "0"), ("web-app-a", "1"), ("web-app-b", "0")],
        )

    def test_the_mode_sorts_in_deploy_order_not_alphabetically(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": mode, "network": "clearnet"}
            for mode in ("host", "swarm", "compose")
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["mode"] for e in ordered], list(axes.MODES))

    def test_clearnet_sorts_ahead_of_tor_ahead_of_multi(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": "compose", "network": state}
            for state in ("multi", "tor", "clearnet")
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["network"] for e in ordered], list(_ALL))

    def test_a_variantless_row_sorts_ahead_of_variant_zero(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": "compose", "network": "tor"},
            {"apps": "web-app-a", "variant": "", "mode": "compose", "network": "tor"},
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["variant"] for e in ordered], ["", "0"])


class TestParseLabel(unittest.TestCase):
    def _title(self, mode: str, app: str, variant: str, **kw) -> str:
        rows = [_row(app, int(variant), (mode,), **kw)]
        return _assign(rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS)[
            0
        ]["label"]

    def test_a_label_round_trips_through_the_parser(self) -> None:
        for mode in ("compose", "swarm", "host"):
            with self.subTest(mode):
                title = self._title(mode, "web-app-a", "0")
                label = axes.parse_label(title)
                self.assertIsNotNone(label)
                self.assertEqual(label.mode, mode)
                self.assertEqual(label.variant, "0")
                self.assertEqual(display_names().decode(label.name), "web-app-a")

    def test_the_network_mode_survives_the_round_trip(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entries = _assign(
            rows, sweep=0, network_input="auto", variants_per_app=_VARIANTS
        )
        parsed = {axes.parse_label(e["label"]).network for e in entries}
        self.assertEqual(parsed, set(_ALL))

    def test_a_host_label_reads_back_as_clearnet(self) -> None:
        title = self._title("host", "web-app-a", "0")
        self.assertEqual(axes.parse_label(title).network, "clearnet")

    def test_the_priority_star_does_not_bleed_into_the_name(self) -> None:
        title = self._title("compose", "web-app-a", "0", priority=True)
        label = axes.parse_label(title)
        self.assertEqual(display_names().decode(label.name), "web-app-a")

    def test_a_reusable_workflow_prefix_is_tolerated(self) -> None:
        title = "🎶 Orchestrate CI / test-deploy-chunk-1 / " + self._title(
            "swarm", "web-app-a", "0"
        )
        self.assertEqual(axes.parse_label(title).mode, "swarm")

    def test_the_distro_and_filesystem_survive_the_round_trip(self) -> None:
        entry = _assign(
            [_row("web-app-a", 0, ("swarm",))],
            sweep=0,
            network_input="multi",
            distros=("centos",),
            filesystems=("btrfs",),
            variants_per_app=_VARIANTS,
        )[0]
        label = axes.parse_label(entry["label"])
        self.assertEqual(
            (label.network, label.distro, label.filesystem),
            ("multi", "centos", "btrfs"),
        )
        self.assertEqual(display_names().decode(label.name), "web-app-a")

    def test_a_non_deploy_job_yields_nothing(self) -> None:
        self.assertIsNone(axes.parse_label("🎲 Pick distro(s)"))
        self.assertIsNone(axes.parse_label("🧹 Lint"))


class TestEnvironmentReads(unittest.TestCase):
    def test_the_sweep_comes_from_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_CI_SWEEP": "3"}):
            self.assertEqual(axes.resolve_sweep(), 3)

    def test_the_network_input_comes_from_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_NETWORK": "multi"}):
            self.assertEqual(network.resolve_network_input(), "multi")


if __name__ == "__main__":
    unittest.main()
