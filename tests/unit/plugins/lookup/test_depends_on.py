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
        # Lines 2+ carry the lookup's `indent` (4) plus YAML's own
        # 2-space nested indent. Line 1 stays unindented so the
        # template caller controls its column via `    {{ ... }}`.
        self.assertIn("      db:\n        condition: service_healthy", out)
        self.assertIn(
            "      init:\n        condition: service_completed_successfully", out
        )

    def test_mapping_with_none_uses_default_condition(self):
        out = _run({"db": None}, variables={"DEPLOYMENT_MODE": "compose"})
        self.assertIn("      db:\n        condition: service_started", out)

    def test_mapping_with_empty_string_uses_default_condition(self):
        # An empty / whitespace-only condition is treated as "unset"
        # so a caller doing ``{SVC: ''}`` does not silently produce a
        # compose file with a literal empty condition.
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
                {"db": "service_healty"},  # typo
                variables={"DEPLOYMENT_MODE": "compose"},
            )

    def test_empty_mapping_returns_empty_string(self):
        out = _run({}, variables={"DEPLOYMENT_MODE": "compose"})
        self.assertEqual(out, "")

    def test_empty_list_returns_empty_string(self):
        out = _run([], variables={"DEPLOYMENT_MODE": "swarm"})
        self.assertEqual(out, "")

    def test_single_string_term_is_rejected(self):
        # Catches the easy typo ``lookup('depends_on', SVC)`` where the
        # caller forgot the list wrapper.
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
        # No conditions leak into swarm output.
        self.assertNotIn("condition:", out)

    def test_compose_emits_map_form(self):
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertIn("db:", out)
        self.assertIn("condition: service_healthy", out)

    def test_unknown_mode_falls_back_to_compose(self):
        # Defending against typos in DEPLOYMENT_MODE so a swarm-shaped
        # cluster does not silently get a compose-shaped file (or vice
        # versa). Compose is the safe default since its `condition:`
        # is at least *parseable* by swarm (it just errors at deploy
        # time, surfacing the problem instead of silently working).
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "kubernetes"},
        )
        self.assertIn("condition: service_healthy", out)

    def test_missing_deployment_mode_defaults_to_compose(self):
        out = _run({"db": "service_healthy"}, variables={})
        self.assertIn("condition: service_healthy", out)

    def test_mode_override_kwarg(self):
        # The mode kwarg is the test-only escape hatch; verify it
        # actually overrides the variable-derived mode so the unit
        # tests can drive both branches without going through the
        # templar.
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
            mode="swarm",
        )
        self.assertIn("- db", out)
        self.assertNotIn("condition:", out)


class TestOutputFormatting(unittest.TestCase):
    def test_compose_block_line1_unindented_lines2plus_indented_by_4(self):
        # Caller writes ``    {{ lookup('depends_on', …) }}`` at column
        # 4. Line 1 contributes no leading whitespace; the template's
        # column-4 placement becomes line 1's indent at render time.
        # Lines 2+ carry the lookup's `indent` (4) so they align under
        # line 1 regardless of Jinja substitution semantics.
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "compose"})
        expected = "depends_on:\n      db:\n        condition: service_healthy"
        self.assertEqual(out, expected)

    def test_swarm_block_line1_unindented_lines2plus_indented_by_4(self):
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "swarm"})
        expected = "depends_on:\n    - db"
        self.assertEqual(out, expected)

    def test_custom_indent_kwarg_only_affects_lines_2_plus(self):
        # indent=6 -> lines 2+ get 6 leading spaces, but line 1 still
        # has none (template controls line 1's column).
        out = _run(
            {"db": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
            indent=6,
        )
        self.assertTrue(out.startswith("depends_on:"))
        self.assertIn("\n        db:", out)  # 6 indent + 2 yaml = 8

    def test_zero_indent_kwarg_keeps_left_edge_on_all_lines(self):
        # indent=0 -> lines 2+ also start at the left edge (raw YAML).
        # Useful for top-level placement with no surrounding service
        # wrapper.
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
        # Output order is meaningful for diff stability; verify dicts
        # render in insertion order rather than YAML-sorted.
        out = _run(
            {"first": "service_started", "second": "service_healthy"},
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        first_pos = out.find("first:")
        second_pos = out.find("second:")
        self.assertGreater(first_pos, -1)
        self.assertGreater(second_pos, first_pos)

    def test_single_entry_swarm_emits_list_item_with_indent(self):
        # Verify the swarm list-form path also leaves line 1
        # unindented and indents the bullet only by `indent`.
        out = _run({"db": "service_healthy"}, variables={"DEPLOYMENT_MODE": "swarm"})
        self.assertEqual(out, "depends_on:\n    - db")


if __name__ == "__main__":
    unittest.main()
