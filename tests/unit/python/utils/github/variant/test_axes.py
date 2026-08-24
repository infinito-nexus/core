from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.github.variant import axes, pools, tor
from utils.roles.display import display_names
from utils.symbol_glossary import to_emoji

_VARIANTS = {
    "web-app-a": [
        {"services": {"tor": {"enabled": True}}},
        {"services": {"tor": {"enabled": False}}},
    ],
    "web-app-b": [{"services": {}}],
}


def _row(name: str, variant: int, modes: tuple[str, ...], **extra) -> dict:
    return {"name": name, "variant": variant, "modes": modes, **extra}


def _assign(rows, **kwargs) -> list[dict[str, str]]:
    """:func:`axes.assign` on the full declared pools, which is what an
    unnarrowed run hands it."""
    kwargs.setdefault("distros", axes.DISTROS)
    kwargs.setdefault("filesystems", axes.FILESYSTEMS)
    return axes.assign(rows, **kwargs)


class TestResolveTorMode(unittest.TestCase):
    def test_known_modes_pass_through(self) -> None:
        for mode in tor.TOR_MODES:
            self.assertEqual(tor.resolve_tor_mode(mode), mode)

    def test_unknown_and_empty_fall_back_to_auto(self) -> None:
        self.assertEqual(tor.resolve_tor_mode("nonsense"), "auto")
        self.assertEqual(tor.resolve_tor_mode(""), "auto")


class TestResolveSweep(unittest.TestCase):
    def test_a_number_is_read(self) -> None:
        self.assertEqual(axes.resolve_sweep("7"), 7)

    def test_garbage_reads_as_zero(self) -> None:
        self.assertEqual(axes.resolve_sweep("x"), 0)
        self.assertEqual(axes.resolve_sweep(""), 0)


class TestTorCapable(unittest.TestCase):
    def test_a_variant_pinning_the_gate_false_is_incapable(self) -> None:
        self.assertFalse(axes.tor_capable("web-app-a", 1, _VARIANTS))

    def test_a_variant_pinning_the_gate_true_is_capable(self) -> None:
        self.assertTrue(axes.tor_capable("web-app-a", 0, _VARIANTS))

    def test_an_unset_gate_counts_as_capable(self) -> None:
        self.assertTrue(axes.tor_capable("web-app-b", 0, _VARIANTS))


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
    def test_a_row_walks_all_four_combinations_in_four_sweeps(self) -> None:
        offered = ("compose", "swarm")
        seen = {
            (axes.pick_mode(offered, 0, sweep), axes.wants_tor(0, sweep))
            for sweep in range(4)
        }
        self.assertEqual(len(seen), 4)


class TestGlyphBinding(unittest.TestCase):
    def test_the_local_glyph_is_the_house_symbol(self) -> None:
        self.assertEqual("🏠", axes.LOCAL_GLYPH)


class TestArtifactSlug(unittest.TestCase):
    def test_the_entry_carries_the_slug_the_reporter_looks_for(self) -> None:
        from cli.meta.ci.report_failures import Failure, artifact_name

        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        for entry in entries:
            with self.subTest(entry["label"]):
                self.assertEqual(
                    f"rescue-diagnostics-{entry['artifact']}",
                    artifact_name(
                        entry["apps"],
                        Failure(
                            entry["mode"],
                            entry["variant"],
                            entry["tor"] == "true",
                            entry["distro"],
                            entry["filesystem"],
                        ),
                    ),
                )

    def test_the_onion_state_keeps_two_runs_of_one_variant_apart(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(len({e["artifact"] for e in entries}), len(entries))

    def test_a_variantless_row_gets_no_dangling_separator(self) -> None:
        self.assertEqual(
            axes.artifact_slug("host", "sys-front-proxy", "", False),
            "host-sys-front-proxy",
        )


class TestTorStates(unittest.TestCase):
    def test_a_capable_tor_mode_covers_both_states_under_auto(self) -> None:
        self.assertEqual(
            axes.tor_states("compose", capable=True, tor_mode="auto"), [True, False]
        )

    def test_an_incapable_row_only_runs_clearnet(self) -> None:
        self.assertEqual(
            axes.tor_states("compose", capable=False, tor_mode="auto"), [False]
        )

    def test_host_carries_no_onion_axis(self) -> None:
        self.assertEqual(
            axes.tor_states("host", capable=True, tor_mode="auto"), [False]
        )

    def test_an_explicit_narrowing_wins_over_full_coverage(self) -> None:
        self.assertEqual(
            axes.tor_states("compose", capable=True, tor_mode="enforced"), [True]
        )
        self.assertEqual(
            axes.tor_states("compose", capable=True, tor_mode="disabled"), [False]
        )

    def test_exclusive_drops_an_incapable_row_entirely(self) -> None:
        self.assertEqual(
            axes.tor_states("compose", capable=False, tor_mode="exclusive"), []
        )


class TestCombinations(unittest.TestCase):
    def test_two_modes_on_the_onion_axis_yield_four_runs(self) -> None:
        self.assertEqual(
            axes.combinations(("compose", "swarm"), capable=True, tor_mode="auto"),
            [
                ("compose", True),
                ("compose", False),
                ("swarm", True),
                ("swarm", False),
            ],
        )

    def test_a_stackless_role_yields_compose_pair_plus_one_host(self) -> None:
        self.assertEqual(
            axes.combinations(("compose", "host"), capable=True, tor_mode="auto"),
            [("compose", True), ("compose", False), ("host", False)],
        )

    def test_an_incapable_variant_halves_the_cross_product(self) -> None:
        self.assertEqual(
            axes.combinations(("compose", "swarm"), capable=False, tor_mode="auto"),
            [("compose", False), ("swarm", False)],
        )


class TestPriorityCoverage(unittest.TestCase):
    def test_a_priority_row_runs_every_combination_in_one_sweep(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(
            {(e["mode"], e["tor"]) for e in entries},
            {
                ("compose", "true"),
                ("compose", "false"),
                ("swarm", "true"),
                ("swarm", "false"),
            },
        )

    def test_a_regular_row_still_takes_exactly_one_combination(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"))]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(len(entries), 1)

    def test_priority_coverage_does_not_move_with_the_sweep(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        shapes = {
            frozenset(
                (e["mode"], e["tor"])
                for e in _assign(
                    rows, sweep=sweep, tor_mode="auto", variants_per_app=_VARIANTS
                )
            )
            for sweep in range(4)
        }
        self.assertEqual(len(shapes), 1)

    def test_every_priority_job_gets_a_distinct_label(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(len({e["label"] for e in entries}), len(entries))

    def test_an_incapable_priority_variant_skips_its_onion_runs(self) -> None:
        rows = [_row("web-app-a", 1, ("compose", "swarm"), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual([e["tor"] for e in entries], ["false", "false"])


class TestAssign(unittest.TestCase):
    def test_every_row_becomes_one_entry(self) -> None:
        rows = [
            _row("web-app-a", 0, ("compose", "swarm")),
            _row("web-app-a", 1, ("compose", "swarm")),
        ]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual([e["variant"] for e in entries], ["0", "1"])

    def test_the_label_opens_with_the_mode_glyph(self) -> None:
        rows = [_row("web-app-a", 0, ("compose",))]
        entry = _assign(rows, sweep=0, tor_mode="disabled", variants_per_app=_VARIANTS)[
            0
        ]
        self.assertTrue(entry["label"].startswith(to_emoji("compose")))

    def test_a_host_row_carries_no_onion_glyph(self) -> None:
        rows = [_row("web-app-b", 0, ("host",))]
        entry = _assign(rows, sweep=0, tor_mode="enforced", variants_per_app=_VARIANTS)[
            0
        ]
        self.assertEqual(entry["tor"], "false")
        self.assertNotIn(to_emoji("tor"), entry["label"])
        self.assertNotIn(to_emoji("clearnet"), entry["label"])

    def test_a_priority_row_wears_the_star(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entry = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)[0]
        self.assertTrue(entry["label"].endswith(to_emoji("priority")))
        self.assertEqual(entry["priority"], "true")

    def test_enforced_onions_every_capable_row(self) -> None:
        rows = [
            _row("web-app-a", 0, ("compose",)),
            _row("web-app-a", 1, ("compose",)),
        ]
        entries = _assign(
            rows, sweep=0, tor_mode="enforced", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["tor"] for e in entries], ["true", "false"])

    def test_disabled_onions_nothing(self) -> None:
        rows = [_row("web-app-a", 0, ("compose",))]
        entries = _assign(
            rows, sweep=0, tor_mode="disabled", variants_per_app=_VARIANTS
        )
        self.assertEqual(entries[0]["tor"], "false")
        self.assertEqual(entries[0]["disable"], "tor")

    def test_exclusive_drops_the_rows_that_cannot_take_an_onion(self) -> None:
        rows = [
            _row("web-app-a", 0, ("compose",)),
            _row("web-app-a", 1, ("compose",)),
        ]
        entries = _assign(
            rows, sweep=0, tor_mode="exclusive", variants_per_app=_VARIANTS
        )
        self.assertEqual([e["variant"] for e in entries], ["0"])

    def test_a_row_without_tor_disables_the_provider(self) -> None:
        rows = [_row("web-app-a", 1, ("compose",))]
        entry = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)[0]
        self.assertEqual(entry["disable"], "tor")

    def test_a_host_row_carries_the_local_glyph_where_tor_rows_carry_theirs(
        self,
    ) -> None:
        entries = _assign(
            [_row("web-app-a", 0, ("host",)), _row("web-app-a", 0, ("compose",))],
            sweep=0,
            tor_mode="enforced",
            variants_per_app=_VARIANTS,
        )
        host, compose = entries
        self.assertTrue(host["label"].startswith(to_emoji("host") + axes.LOCAL_GLYPH))
        self.assertTrue(
            compose["label"].startswith(to_emoji("compose") + to_emoji("tor"))
        )
        self.assertEqual(axes.parse_label(host["label"]).mode, "host")

    def test_the_provider_row_never_takes_the_clearnet_state(self) -> None:
        provider = axes.tor_provider()
        self.assertIsNotNone(provider)
        for sweep in range(4):
            for tor_mode in tor.TOR_MODES:
                with self.subTest(sweep=sweep, tor_mode=tor_mode):
                    entries = _assign(
                        [_row(provider, 0, ("compose", "swarm"), priority=True)],
                        sweep=sweep,
                        tor_mode=tor_mode,
                    )
                    self.assertEqual(
                        [e["disable"] for e in entries], [""] * len(entries)
                    )
                    self.assertNotIn("false", [e["tor"] for e in entries])


class TestPinnedAxes(unittest.TestCase):
    def _entries(self, row: dict) -> list[dict[str, str]]:
        return _assign([row], sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)

    def test_a_pinned_mode_replaces_the_rotation(self) -> None:
        row = _row("web-app-b", 0, ("compose", "swarm"), pin_mode="swarm")
        self.assertEqual([e["mode"] for e in self._entries(row)], ["swarm"])

    def test_a_pinned_onion_state_replaces_the_rotation(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_tor=True)
        self.assertEqual([e["tor"] for e in self._entries(row)], ["true"])

    def test_an_open_axis_still_rotates(self) -> None:
        row = _row("web-app-b", 0, ("compose", "swarm"), pin_tor=False)
        picks = {
            _assign([row], sweep=sweep, tor_mode="auto", variants_per_app=_VARIANTS)[0][
                "mode"
            ]
            for sweep in range(2)
        }
        self.assertEqual(picks, {"compose", "swarm"})

    def test_pinning_the_onion_keeps_the_rotation_off_host(self) -> None:
        row = _row("web-app-b", 0, ("compose", "host"), pin_tor=True)
        for sweep in range(4):
            with self.subTest(sweep=sweep):
                entries = _assign(
                    [row], sweep=sweep, tor_mode="auto", variants_per_app=_VARIANTS
                )
                self.assertEqual([e["mode"] for e in entries], ["compose"])

    def test_a_pin_narrows_the_priority_cross_product(self) -> None:
        row = _row(
            "web-app-b", 0, ("compose", "swarm"), priority=True, pin_mode="compose"
        )
        entries = self._entries(row)
        self.assertEqual(
            {(e["mode"], e["tor"]) for e in entries},
            {("compose", "true"), ("compose", "false")},
        )

    def test_a_fully_pinned_priority_row_runs_exactly_once(self) -> None:
        row = _row(
            "web-app-b",
            0,
            ("compose", "swarm"),
            priority=True,
            pin_mode="swarm",
            pin_tor=False,
        )
        self.assertEqual(len(self._entries(row)), 1)

    def test_an_unoffered_mode_aborts_the_matrix(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_mode="swarm")
        with self.assertRaises(SystemExit):
            self._entries(row)

    def test_an_impossible_onion_state_aborts_the_matrix(self) -> None:
        row = _row("web-app-a", 1, ("compose",), pin_tor=True)
        with self.assertRaises(SystemExit):
            self._entries(row)

    def test_a_pin_fighting_the_runs_tor_axis_aborts(self) -> None:
        row = _row("web-app-b", 0, ("compose",), pin_tor=True)
        with self.assertRaises(SystemExit):
            _assign([row], sweep=0, tor_mode="disabled", variants_per_app=_VARIANTS)


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
            tor_mode="auto",
            variants_per_app=_VARIANTS,
        )
        self.assertEqual([e["distro"] for e in entries], list(axes.DISTROS))

    def test_the_sweep_moves_every_row_on_to_the_next_distro(self) -> None:
        picks = [
            _assign(
                self._rows(1), sweep=sweep, tor_mode="auto", variants_per_app=_VARIANTS
            )[0]["distro"]
            for sweep in range(len(axes.DISTROS))
        ]
        self.assertEqual(set(picks), set(axes.DISTROS))

    def test_a_narrowed_pool_is_the_only_thing_drawn_from(self) -> None:
        entries = _assign(
            self._rows(4),
            sweep=0,
            tor_mode="auto",
            distros=("debian",),
            filesystems=("btrfs",),
            variants_per_app=_VARIANTS,
        )
        self.assertEqual({e["distro"] for e in entries}, {"debian"})
        self.assertEqual({e["filesystem"] for e in entries}, {"btrfs"})

    def test_a_priority_row_spreads_its_combinations_over_the_pool(self) -> None:
        rows = [_row("web-app-b", 0, ("compose", "swarm"), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(len({e["distro"] for e in entries}), len(entries))

    def test_a_pinned_distro_replaces_the_rotation(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), pin_distro="fedora")]
        entries = _assign(rows, sweep=3, tor_mode="auto", variants_per_app=_VARIANTS)
        self.assertEqual(entries[0]["distro"], "fedora")

    def test_a_pinned_filesystem_replaces_the_rotation(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), pin_filesystem="ext4")]
        entries = _assign(rows, sweep=1, tor_mode="auto", variants_per_app=_VARIANTS)
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
            tor_mode="disabled",
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
                tor_mode="auto",
                distros=("debian",),
                variants_per_app=_VARIANTS,
            )

    def test_the_glyphs_follow_the_onion_slot_in_the_label(self) -> None:
        entry = _assign(
            [_row("web-app-b", 0, ("compose",))],
            sweep=0,
            tor_mode="disabled",
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
        return _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)

    def test_rows_sort_by_name_then_variant(self) -> None:
        ordered = sorted(self._entries(), key=axes.sort_key)
        self.assertEqual(
            [(e["apps"], e["variant"]) for e in ordered],
            [("web-app-a", "0"), ("web-app-a", "1"), ("web-app-b", "0")],
        )

    def test_the_mode_sorts_in_deploy_order_not_alphabetically(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": mode, "tor": "false"}
            for mode in ("host", "swarm", "compose")
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["mode"] for e in ordered], list(axes.MODES))

    def test_clearnet_sorts_ahead_of_the_onion(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": "compose", "tor": tor}
            for tor in ("true", "false")
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["tor"] for e in ordered], ["false", "true"])

    def test_a_variantless_row_sorts_ahead_of_variant_zero(self) -> None:
        entries = [
            {"apps": "web-app-a", "variant": "0", "mode": "compose", "tor": "false"},
            {"apps": "web-app-a", "variant": "", "mode": "compose", "tor": "false"},
        ]
        ordered = sorted(entries, key=axes.sort_key)
        self.assertEqual([e["variant"] for e in ordered], ["", "0"])


class TestParseLabel(unittest.TestCase):
    def _title(self, mode: str, app: str, variant: str, **kw) -> str:
        rows = [_row(app, int(variant), (mode,), **kw)]
        return _assign(rows, sweep=0, tor_mode="enforced", variants_per_app=_VARIANTS)[
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

    def test_the_onion_state_survives_the_round_trip(self) -> None:
        rows = [_row("web-app-b", 0, ("compose",), priority=True)]
        entries = _assign(rows, sweep=0, tor_mode="auto", variants_per_app=_VARIANTS)
        parsed = {axes.parse_label(e["label"]).tor for e in entries}
        self.assertEqual(parsed, {True, False})

    def test_a_host_label_reads_back_as_clearnet(self) -> None:
        title = self._title("host", "web-app-a", "0")
        self.assertFalse(axes.parse_label(title).tor)

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
            tor_mode="enforced",
            distros=("centos",),
            filesystems=("btrfs",),
            variants_per_app=_VARIANTS,
        )[0]
        label = axes.parse_label(entry["label"])
        self.assertEqual((label.distro, label.filesystem), ("centos", "btrfs"))
        self.assertEqual(display_names().decode(label.name), "web-app-a")

    def test_a_non_deploy_job_yields_nothing(self) -> None:
        self.assertIsNone(axes.parse_label("🎲 Pick distro(s)"))
        self.assertIsNone(axes.parse_label("🧹 Lint"))


class TestEnvironmentReads(unittest.TestCase):
    def test_the_sweep_comes_from_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_CI_SWEEP": "3"}):
            self.assertEqual(axes.resolve_sweep(), 3)

    def test_the_tor_mode_comes_from_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_TOR": "exclusive"}):
            self.assertEqual(tor.resolve_tor_mode(), "exclusive")


if __name__ == "__main__":
    unittest.main()
