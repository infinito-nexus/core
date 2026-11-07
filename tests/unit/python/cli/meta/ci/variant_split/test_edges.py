from __future__ import annotations

import unittest

from cli.meta.ci.variant_split.edges import (
    Edge,
    identities,
    is_active,
    missing,
    round_edges,
    sharing,
    union,
)

PROVIDERS = {"sso": "keycloak", "db": "postgres", "matrix": "matrix"}


def _edges(maps, include, active=None, mcp=()):
    return round_edges(
        include=include,
        maps=maps,
        active_index=active or {},
        provider_of=PROVIDERS.get,
        mcp_pairs=mcp,
    )


class TestActivity(unittest.TestCase):
    def test_a_literal_false_or_empty_flag_is_off(self) -> None:
        self.assertFalse(is_active({"enabled": False}))
        self.assertFalse(is_active({"enabled": "false"}))
        self.assertFalse(is_active({"enabled": ""}))
        self.assertFalse(is_active("not a mapping"))

    def test_a_presence_gate_or_a_missing_flag_counts_as_on(self) -> None:
        self.assertTrue(is_active({"enabled": "{{ 'x' in group_names }}"}))
        self.assertTrue(is_active({"shared": True}))

    def test_sharing_is_normalised(self) -> None:
        self.assertEqual(sharing({"shared": True}), "shared")
        self.assertEqual(sharing({"shared": False}), "dedicated")
        self.assertEqual(sharing({"enabled": True}), "unset")


class TestRoundEdges(unittest.TestCase):
    def test_only_active_keys_to_deployed_providers_become_edges(self) -> None:
        maps = {
            "app": {
                "sso": {"enabled": True, "shared": True},
                "db": {"enabled": False},
                "matrix": {"enabled": True, "shared": True},
            }
        }
        edges = _edges(maps, ["app", "keycloak", "postgres"])
        self.assertEqual(edges, {Edge("app", 0, "sso", "keycloak", 0, "shared")})

    def test_mcp_pairs_count_only_when_both_ends_are_deployed(self) -> None:
        edges = _edges(
            {}, ["client", "server"], mcp=[("client", "server"), ("client", "gone")]
        )
        self.assertEqual(
            {(e.consumer, e.key, e.provider) for e in edges},
            {("client", "mcp", "server")},
        )


OLD = frozenset(
    {
        Edge("app", 0, "sso", "keycloak", 0, "shared"),
        Edge("app", 0, "db", "postgres", 0, "shared"),
    }
)
OIDC = Edge("app", 0, "oidc", "keycloak", 0, "shared")


class TestMissing(unittest.TestCase):
    def test_a_carrier_with_the_same_edges_leaves_nothing_missing(self) -> None:
        self.assertEqual(missing([OLD], [OLD], "strict"), set())

    def test_negative_control_an_extra_key_breaks_the_keys_level_only(self) -> None:
        carrier = OLD | {OIDC}
        self.assertEqual(missing([OLD], [carrier], "pair"), set())
        self.assertEqual(
            missing([OLD], [carrier], "keys"),
            {("app", "keycloak", frozenset({("sso", "shared")}))},
        )

    def test_negative_control_a_moved_variant_breaks_the_strict_level_only(
        self,
    ) -> None:
        carrier = {
            Edge(c, cv, k, p, 2 if p == "postgres" else pv, s)
            for c, cv, k, p, pv, s in OLD
        }
        self.assertEqual(missing([OLD], [carrier], "keys"), set())
        self.assertEqual(len(missing([OLD], [carrier], "strict")), 1)

    def test_edges_split_over_two_carriers_are_all_held(self) -> None:
        first, second = sorted(OLD)
        self.assertEqual(missing([OLD], [{first}, {second}], "keys"), set())

    def test_negative_control_a_carrier_missing_one_edge_leaves_it_missing(
        self,
    ) -> None:
        first, _second = sorted(OLD)
        self.assertEqual(len(missing([OLD], [{first}], "keys")), 1)

    def test_two_old_rounds_keep_their_key_sets_apart(self) -> None:
        sso = {e for e in OLD if e.key == "sso"}
        self.assertEqual(missing([sso, {OIDC}], [sso, {OIDC}], "keys"), set())

    def test_the_union_collapses_each_round_on_its_own(self) -> None:
        sso = {e for e in OLD if e.key == "sso"}
        self.assertEqual(
            union([sso, {OIDC}], "keys"),
            {
                ("app", "keycloak", frozenset({("sso", "shared")})),
                ("app", "keycloak", frozenset({("oidc", "shared")})),
            },
        )

    def test_an_unknown_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            identities(OLD, "loose")


if __name__ == "__main__":
    unittest.main()
