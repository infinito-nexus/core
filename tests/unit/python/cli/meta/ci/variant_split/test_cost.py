from __future__ import annotations

import unittest

from cli.meta.ci.variant_split import cost

from . import entry, record, row, snapshot

SEGMENTS = {
    "passes": {"1": {"app": 100.0, "heavy": 900.0}, "2": {"app": 10.0, "heavy": 20.0}},
    "fixed": {
        "prep": 0,
        "container": 0,
        "backup": 0,
        "reset_post": 0,
        "infra_per_pass": 0,
        "dr_drill_variant0": 50,
    },
    "runner": "r1",
}


class TestRowCost(unittest.TestCase):
    def test_a_row_sums_its_apps_per_pass_plus_its_fixed_cost(self) -> None:
        seconds, unpriced = cost.row_cost(["app", "heavy"], 0, SEGMENTS)
        self.assertEqual(seconds, 50 + 110 + 920)
        self.assertEqual(unpriced, [])

    def test_only_variant_0_pays_the_dr_drill(self) -> None:
        self.assertEqual(cost.row_cost(["app"], 3, SEGMENTS)[0], 110)

    def test_negative_control_an_unmeasured_app_is_listed_not_hidden(self) -> None:
        seconds, unpriced = cost.row_cost(["app", "new"], 3, SEGMENTS)
        self.assertEqual(seconds, 110)
        self.assertEqual(unpriced, ["new"])

    def test_the_default_fixed_cost_is_the_measured_per_row_overhead(self) -> None:
        seconds, _ = cost.row_cost([], 0, {"passes": {"1": {}, "2": {}}})
        self.assertEqual(seconds, 273 + 204 + 340 + 170 + 2 * 540 + 152)


class TestDelta(unittest.TestCase):
    def test_a_split_reports_the_saving_and_the_added_runner_time(self) -> None:
        before = snapshot(
            [row("app#0", 1)],
            {"app#0": record(["heavy", "app"])},
            head=[entry("app#0")],
            jobs=["app#0"],
        )
        after = snapshot(
            [row("app#0", 1), row("app#3", 2)],
            {"app#0": record(["app"]), "app#3": record(["heavy", "app"])},
            head=[entry("app#0"), entry("app#3")],
            jobs=["app#0", "app#3"],
        )
        result = cost.delta(
            before, after, SEGMENTS, old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["rows"]["app#0"]["saving"], 920)
        self.assertEqual(result["net"]["jobs"]["delta"], (160 + 1030) - 1080)
        self.assertIn("app#3", cost.render(result))

    def test_the_render_names_the_runner_the_segments_came_from(self) -> None:
        snap = snapshot(
            [row("app#0", 1)], {"app#0": record(["app"])}, head=[], jobs=["app#0"]
        )
        result = cost.delta(snap, snap, SEGMENTS, old=["app#0"], split=["app#0"])
        self.assertIn("on runner r1", cost.render(result))


if __name__ == "__main__":
    unittest.main()
