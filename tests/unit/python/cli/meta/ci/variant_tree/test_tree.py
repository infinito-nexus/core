from __future__ import annotations

import unittest

from cli.meta.ci.variant_tree import tree

PINNED = {"b": "a#0"}
GATE = "{{ 'x' in group_names }}"
TREE = {
    "primary": "a#0",
    "round_index": 0,
    "include_count": 2,
    "error": None,
    "nodes": [
        {
            "role": "b",
            "variant": 1,
            "variants": 2,
            "reason": "pin by a#0",
            "services": [],
            "children": [],
        },
        {
            "role": "a",
            "variant": 0,
            "variants": 1,
            "reason": "primary",
            "services": [
                {"key": "k", "provider": "b", "state": "required", "deployed": True}
            ],
            "children": ["b"],
        },
    ],
}


def _reason(role: str, index: int, count: int) -> str:
    return tree.reason(role, primary="a", index=index, count=count, pinned=PINNED)


class TestReason(unittest.TestCase):
    def test_the_primary_is_named_first(self) -> None:
        self.assertEqual(_reason("a", 0, 3), "primary")

    def test_a_pin_in_force_names_its_carrier(self) -> None:
        self.assertEqual(_reason("b", 0, 3), "pin by a#0")

    def test_a_role_with_that_many_variants_follows_the_round_index(self) -> None:
        self.assertEqual(_reason("c", 2, 3), "round index")

    def test_a_round_past_the_roles_variants_falls_back_to_0(self) -> None:
        self.assertEqual(_reason("c", 5, 3), "default 0: round past its variants")

    def test_a_single_variant_role_past_round_0_falls_back_to_0(self) -> None:
        self.assertEqual(_reason("d", 1, 1), "default 0: round past its variants")


class TestState(unittest.TestCase):
    def test_a_literal_false_is_off(self) -> None:
        self.assertEqual(tree.state({"enabled": False}, None), "off")

    def test_a_key_true_in_both_maps_is_required(self) -> None:
        self.assertEqual(tree.state({"enabled": True}, {"enabled": True}), "required")

    def test_a_key_true_only_in_the_round_is_forced_by_override(self) -> None:
        self.assertEqual(
            tree.state({"enabled": True}, {"enabled": GATE}), "forced by override"
        )

    def test_a_group_names_gate_is_presence_gated(self) -> None:
        self.assertEqual(tree.state({"enabled": GATE}, None), "presence-gated")

    def test_a_key_without_enabled_is_implicit(self) -> None:
        self.assertEqual(tree.state({"shared": True}, None), "implicit")


class TestRender(unittest.TestCase):
    def test_the_header_names_the_closure_size(self) -> None:
        lines = tree.render_text(TREE).splitlines()
        self.assertEqual(lines[0], "a#0: include 2 (resolve_round), round index 0")

    def test_the_primary_leads_and_its_providers_nest_below(self) -> None:
        lines = tree.render_text(TREE).splitlines()
        self.assertEqual(
            (lines[1], lines[3]), ("a#0/1 [primary]", "  b#1/2 [pin by a#0]")
        )

    def test_an_error_replaces_the_tree(self) -> None:
        text = tree.render_text({**TREE, "error": "pins cycle", "nodes": []})
        self.assertIn("error: pins cycle", text)


class TestToken(unittest.TestCase):
    def test_a_bare_role_is_variant_0(self) -> None:
        self.assertEqual(tree.parse_token("web-app-a"), ("web-app-a", 0))

    def test_a_token_keeps_its_variant(self) -> None:
        self.assertEqual(tree.parse_token("web-app-a#7"), ("web-app-a", 7))


FOUR = {"web-app-a": [{}, {}, {}, {}]}


class TestBuildRange(unittest.TestCase):
    def test_negative_control_a_variant_past_the_last_names_the_valid_range(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, r"4 variant\(s\).*must be 0\.\.3"):
            tree.build("web-app-a#9", roles_dir="/roles", variants_per_app=FOUR)

    def test_negative_control_an_unknown_role_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no role 'web-app-z'"):
            tree.build("web-app-z#0", roles_dir="/roles", variants_per_app=FOUR)


if __name__ == "__main__":
    unittest.main()
