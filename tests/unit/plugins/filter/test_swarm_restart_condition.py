"""Unit tests for the ``swarm_restart_condition`` filter.

The filter is consumed by
``roles/sys-svc-container/templates/deploy.yml.j2`` to translate
compose-style ``docker_restart_policy`` values to swarm's
``deploy.restart_policy.condition``. The mapping has only three
output buckets, but the input surface is wider -- typos, the
``on-failure:N`` suffix form, and the None / empty fallback all need
to map correctly so a misconfigured role does not silently produce a
one-shot service when it meant long-running (or vice versa).
"""

from __future__ import annotations

import unittest

from plugins.filter.swarm_restart_condition import (
    FilterModule,
    swarm_restart_condition,
)


class TestSwarmRestartCondition(unittest.TestCase):
    def test_no_maps_to_none(self):
        # The single most important mapping: one-shot bootstrap
        # containers (matomo, erpnext configurator, shopware init)
        # must NOT respawn after exit 0.
        self.assertEqual(swarm_restart_condition("no"), "none")

    def test_on_failure_maps_to_on_failure(self):
        self.assertEqual(swarm_restart_condition("on-failure"), "on-failure")

    def test_on_failure_with_count_suffix_maps_to_on_failure(self):
        # Compose supports `on-failure:5`; swarm has no suffix on the
        # condition itself (max_attempts is a sibling key), so the
        # suffix is dropped.
        self.assertEqual(swarm_restart_condition("on-failure:5"), "on-failure")
        self.assertEqual(swarm_restart_condition("on-failure:0"), "on-failure")

    def test_always_maps_to_any(self):
        self.assertEqual(swarm_restart_condition("always"), "any")

    def test_unless_stopped_maps_to_any(self):
        self.assertEqual(swarm_restart_condition("unless-stopped"), "any")

    def test_none_value_maps_to_any(self):
        # Defending against `docker_restart_policy | default('')` and
        # similar -- the safe default is long-running.
        self.assertEqual(swarm_restart_condition(None), "any")

    def test_empty_string_maps_to_any(self):
        self.assertEqual(swarm_restart_condition(""), "any")
        self.assertEqual(swarm_restart_condition("   "), "any")

    def test_unknown_value_maps_to_any(self):
        # A typo in a role's `docker_restart_policy` must NOT
        # silently become `none` (one-shot) -- that would hide the
        # bug. `any` keeps the service running and the operator
        # notices the typo via the literal `condition: any` in the
        # rendered file.
        self.assertEqual(swarm_restart_condition("alwayss"), "any")
        self.assertEqual(swarm_restart_condition("yes"), "any")
        self.assertEqual(swarm_restart_condition("nope"), "any")

    def test_value_is_stringified(self):
        # The filter should not crash on a non-string input that
        # happens to stringify to a known value (e.g. some lookups
        # return numeric strings).
        self.assertEqual(swarm_restart_condition(0), "any")

    def test_value_is_stripped(self):
        # Stray whitespace from a YAML literal must not defeat the
        # mapping.
        self.assertEqual(swarm_restart_condition("  no  "), "none")
        self.assertEqual(swarm_restart_condition("\tno\n"), "none")
        self.assertEqual(swarm_restart_condition(" on-failure:3 "), "on-failure")

    def test_output_is_always_a_valid_swarm_condition(self):
        # Property: the filter NEVER returns anything outside swarm's
        # closed set, even for garbage input. This is the invariant
        # that makes the rendered compose.yml deploy-safe.
        for raw in [
            None,
            "",
            "no",
            "on-failure",
            "on-failure:7",
            "always",
            "unless-stopped",
            "garbage",
            42,
            -1,
            "  ",
            "yes",
        ]:
            self.assertIn(
                swarm_restart_condition(raw),
                {"none", "on-failure", "any"},
                msg=f"input {raw!r} produced an unexpected output",
            )


class TestFilterModule(unittest.TestCase):
    def test_filter_is_registered_under_its_name(self):
        # Catches accidental rename / typo in the FilterModule shim
        # so consumers in Jinja templates do not silently fall back
        # to the identity filter.
        filters = FilterModule().filters()
        self.assertIn("swarm_restart_condition", filters)
        self.assertIs(filters["swarm_restart_condition"], swarm_restart_condition)


if __name__ == "__main__":
    unittest.main()
