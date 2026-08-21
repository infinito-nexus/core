from __future__ import annotations

import unittest

from cli.meta.ci import query


class TestResolveModes(unittest.TestCase):
    def test_auto_means_every_mode(self) -> None:
        self.assertEqual(query.resolve_modes("auto"), query.MODES)

    def test_empty_means_every_mode(self) -> None:
        self.assertEqual(query.resolve_modes("  "), query.MODES)

    def test_a_subset_keeps_the_canonical_order(self) -> None:
        self.assertEqual(query.resolve_modes("swarm compose"), ("compose", "swarm"))

    def test_commas_separate_like_spaces(self) -> None:
        self.assertEqual(query.resolve_modes("host,swarm"), ("swarm", "host"))

    def test_a_single_mode_stays_alone(self) -> None:
        self.assertEqual(query.resolve_modes("host"), ("host",))

    def test_an_unknown_mode_aborts_instead_of_narrowing_silently(self) -> None:
        with self.assertRaises(SystemExit):
            query.resolve_modes("swrm")


class TestBuildFilter(unittest.TestCase):
    def test_one_mode_needs_no_parentheses(self) -> None:
        self.assertEqual(query.build_filter(("swarm",)), "test_swarm == true")

    def test_several_modes_are_an_or_group(self) -> None:
        self.assertEqual(
            query.build_filter(("compose", "swarm")),
            "(test_compose == true or test_swarm == true)",
        )

    def test_the_whitelist_is_a_membership_clause(self) -> None:
        self.assertIn(
            "name %% {web-app-a,web-app-b}",
            query.build_filter(("swarm",), "web-app-a web-app-b"),
        )

    def test_the_blacklist_is_negated(self) -> None:
        self.assertIn(
            "not (name %% {web-app-a})",
            query.build_filter(("swarm",), "", "web-app-a"),
        )

    def test_an_empty_selection_adds_no_clause(self) -> None:
        self.assertEqual(query.build_filter(("host",), "", ""), "test_host == true")


class TestRowModes(unittest.TestCase):
    def test_only_the_modes_the_row_claims_survive(self) -> None:
        row = {"test_compose": True, "test_swarm": True, "test_host": False}
        self.assertEqual(query.row_modes(row), ("compose", "swarm"))

    def test_the_selection_narrows_the_offer(self) -> None:
        row = {"test_compose": True, "test_swarm": True, "test_host": False}
        self.assertEqual(query.row_modes(row, ("swarm",)), ("swarm",))

    def test_a_stackless_role_offers_host_not_swarm(self) -> None:
        row = {"test_compose": True, "test_swarm": False, "test_host": True}
        self.assertEqual(query.row_modes(row), ("compose", "host"))


class TestToken(unittest.TestCase):
    def test_a_row_becomes_a_role_variant_token(self) -> None:
        self.assertEqual(
            query.token({"name": "web-app-x", "variant": 2}), "web-app-x#2"
        )


class TestSortSpec(unittest.TestCase):
    def test_clones_sort_last_ahead_of_the_declared_spec(self) -> None:
        self.assertTrue(query.sort_spec().startswith("asc clone"))


class TestQueryArgv(unittest.TestCase):
    """Every human-facing view renders through this argv, so a hand-rolled
    --sort/--filter elsewhere cannot drift away from what CI discovers."""

    def _argv(self, **kwargs) -> list[str]:
        return query._query_argv(
            ("compose",), whitelist="", blacklist="", lifecycles="", fmt=[], **kwargs
        )

    def test_the_row_basis_is_the_variant(self) -> None:
        self.assertIn("--variant", self._argv())

    def test_the_role_view_drops_only_the_variant_flag(self) -> None:
        roles = self._argv(variant=False)
        self.assertNotIn("--variant", roles)
        self.assertEqual(
            [roles[roles.index(flag) + 1] for flag in ("--sort", "--filter")],
            [query.sort_spec(), query.build_filter(("compose",))],
        )

    def test_the_filter_reads_the_tested_column_not_the_capable_one(self) -> None:
        argv = self._argv()
        self.assertIn("test_compose == true", argv[argv.index("--filter") + 1])


if __name__ == "__main__":
    unittest.main()
