"""Unit tests for the ``depends_on`` lookup.

Covers the four orthogonal axes:

* input shape  -- mapping vs. list-of-names vs. empty vs. malformed
* DEPLOYMENT_MODE -- compose (default) vs. swarm vs. unknown-falls-to-compose
* condition validation -- explicit valid conditions, None -> default,
  custom default override, rejection of typos like ``service_healty``
* output formatting -- indentation, empty-input passthrough, sort
  stability of multiple entries
"""

from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from plugins.lookup.depends_on import LookupModule


class _StubTemplar:
    def __init__(self, variables: dict[str, object]) -> None:
        self.available_variables = variables

    def template(self, value: object) -> object:
        return value


def _run(
    term: object,
    *,
    variables: dict[str, object] | None = None,
    **kwargs: object,
) -> str:
    """Drive the lookup the way ansible-lookup would and return the
    single emitted string."""
    lookup = LookupModule()
    lookup._templar = _StubTemplar(variables or {})
    out = lookup.run([term], variables=variables or {}, **kwargs)
    assert isinstance(out, list) and len(out) == 1, f"unexpected return: {out!r}"
    return out[0]


class TestInputNormalisation(unittest.TestCase):
    def test_mapping_with_explicit_conditions(self):
        out = _run(
            {"db": "service_healthy", "init": "service_completed_successfully"},
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertIn("      db:\n        condition: service_healthy", out)
        self.assertIn(
            "      init:\n        condition: service_completed_successfully", out
        )

    def test_mapping_with_none_uses_default_condition(self):
        out = _run({"db": None}, variables={"DEPLOYMENT_MODE": "compose"})
        self.assertIn("      db:\n        condition: service_started", out)

    def test_mapping_with_empty_string_uses_default_condition(self):
        out = _run({"db": "   "}, variables={"DEPLOYMENT_MODE": "compose"})
        self.assertIn("      db:\n        condition: service_started", out)

    def test_list_of_names_all_get_default_condition(self):
        out = _run(["db", "redis"], variables={"DEPLOYMENT_MODE": "compose"})
        self.assertIn("      db:\n        condition: service_started", out)
        self.assertIn("      redis:\n        condition: service_started", out)

    def test_custom_default_condition_kwarg(self):
        out = _run(
            ["db", "redis"],
            variables={"DEPLOYMENT_MODE": "compose"},
            default_condition="service_healthy",
        )
        self.assertIn("      db:\n        condition: service_healthy", out)
        self.assertIn("      redis:\n        condition: service_healthy", out)

    def test_invalid_default_condition_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "default_condition.*not a valid"):
            _run(
                ["db"],
                variables={"DEPLOYMENT_MODE": "compose"},
                default_condition="service_typoed",
            )

    def test_invalid_condition_in_mapping_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "invalid condition"):
            _run(
                {"db": "service_healty"},
                variables={"DEPLOYMENT_MODE": "compose"},
            )

    def test_empty_mapping_returns_empty_string(self):
        out = _run({}, variables={"DEPLOYMENT_MODE": "compose"})
        self.assertEqual(out, "")

    def test_empty_list_returns_empty_string(self):
        out = _run([], variables={"DEPLOYMENT_MODE": "swarm"})
        self.assertEqual(out, "")

    def test_single_string_term_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "single string"):
            _run("db", variables={"DEPLOYMENT_MODE": "compose"})

    def test_unsupported_term_type_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "must be a mapping.*or a list"):
            _run(42, variables={"DEPLOYMENT_MODE": "compose"})

    def test_empty_dependency_name_in_mapping_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "non-empty string"):
            _run({"   ": "service_healthy"}, variables={"DEPLOYMENT_MODE": "compose"})

    def test_empty_dependency_name_in_list_is_rejected(self):
        with self.assertRaisesRegex(AnsibleError, "non-empty string"):
            _run([""], variables={"DEPLOYMENT_MODE": "compose"})

    def test_missing_term_is_rejected(self):
        lookup = LookupModule()
        lookup._templar = _StubTemplar({})
        with self.assertRaisesRegex(AnsibleError, "exactly 1 positional term"):
            lookup.run([], variables={})

    def test_too_many_terms_is_rejected(self):
        lookup = LookupModule()
        lookup._templar = _StubTemplar({})
        with self.assertRaisesRegex(AnsibleError, "exactly 1 positional term"):
            lookup.run([["a"], ["b"]], variables={})


class TestModeBehaviour(unittest.TestCase):
    def test_swarm_emits_list_form(self):
        out = _run(
            {"db": "service_healthy", "init": "service_completed_successfully"},
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertIn("depends_on:", out)
        self.assertIn("- db", out)
        self.assertIn("- init", out)
        self.assertNotIn("condition:", out)

    def test_compose_emits_map_form(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertIn("db:", out)
        self.assertIn("condition: service_healthy", out)

    def test_unknown_mode_falls_back_to_compose(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "kubernetes"},
        )
        self.assertIn("condition: service_healthy", out)

    def test_missing_deployment_mode_defaults_to_compose(self):
        out = _run({"db": "service_healthy"}, variables={})
        self.assertIn("condition: service_healthy", out)

    def test_mode_override_kwarg(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
            mode="swarm",
        )
        self.assertIn("- db", out)
        self.assertNotIn("condition:", out)


class TestOutputFormatting(unittest.TestCase):
    def test_compose_block_line1_unindented_lines2plus_indented_by_4(self):
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "compose"})
        expected = "depends_on:\n      db:\n        condition: service_healthy"
        self.assertEqual(out, expected)

    def test_swarm_block_line1_unindented_lines2plus_indented_by_4(self):
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "swarm"})
        expected = "depends_on:\n    - db"
        self.assertEqual(out, expected)

    def test_custom_indent_kwarg_only_affects_lines_2_plus(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
            indent=6,
        )
        self.assertTrue(out.startswith("depends_on:"))
        self.assertIn("\n        db:", out)  # 6 indent + 2 yaml = 8

    def test_zero_indent_kwarg_keeps_left_edge_on_all_lines(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
            indent=0,
        )
        self.assertTrue(out.startswith("depends_on:"))
        self.assertIn("\n  db:", out)  # 0 indent + 2 yaml = 2

    def test_indent_must_be_int(self):
        with self.assertRaisesRegex(AnsibleError, "indent must be an int"):
            _run(
                {"db": "service_healthy"},
                variables={"DEPLOYMENT_MODE": "compose"},
                indent="four",
            )

    def test_multiple_entries_preserve_insertion_order(self):
        out = _run(
            {"first": "service_started", "second": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        first_pos = out.find("first:")
        second_pos = out.find("second:")
        self.assertGreater(first_pos, -1)
        self.assertGreater(second_pos, first_pos)

    def test_single_entry_swarm_emits_list_item_with_indent(self):
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "swarm"})
        self.assertEqual(out, "depends_on:\n    - db")


if __name__ == "__main__":
    unittest.main()
