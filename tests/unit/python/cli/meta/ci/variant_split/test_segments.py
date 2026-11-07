from __future__ import annotations

import unittest

from cli.meta.ci.variant_split import segments

TSV = (
    "500\t0\tTOTAL\n"
    "100\t1\tweb-app-a : own task\n"
    "40\t1\tsys-svc-compose : Ensure instance dir for 'web-app-b' is up\n"
    "30\t1\tsys-svc-compose : Render /opt/compose/b/compose.yml\n"
    "60\t3\tsys-svc-compose : swarm: wait until stack tasks converge\n"
    "20\t1\tsetup roles in run_after order\n"
    "10\t1\tsys-x : touches 'web-app-a' and 'web-app-b'"
)
LOG = [
    "2026-11-06T10:00:00.0Z TASK [prepare the host] ***",
    "2026-11-06T10:00:10.0Z TASK [web-app-a : first] ***",
    "secret=hunter2 must never surface",
    "2026-11-06T10:00:40.0Z TASK [sys-svc-compose : helper for b] ***",
    "2026-11-06T10:01:00.0Z TASK [web-app-b : first] ***",
    "2026-11-06T10:01:05.5Z RUNNING HANDLER [web-app-a : late handler] ***",
    "2026-11-06T10:02:00.0Z TASK [test-e2e-playwright : run] ***",
    "2026-11-06T10:05:00.0Z TASK [test-e2e-playwright : collect] ***",
]
APPS = ["web-app-a", "web-app-b", "web-app-c"]


def _entity(app: str) -> str:
    return app.rsplit("-", 1)[1]


def _file(runner: str, passes: dict, source: str = "s", cut: bool = False) -> dict:
    return {"source": source, "runner": runner, "lower_bound": cut, "passes": passes}


class TestSegments(unittest.TestCase):
    def test_parse_skips_the_total_line(self) -> None:
        self.assertEqual(len(segments.parse_tsv(TSV)), 6)

    def test_tasks_are_attributed_by_prefix_mention_spread_or_fixed(self) -> None:
        result = segments.attribute(segments.parse_tsv(TSV), APPS, entity_of=_entity)
        self.assertEqual(
            result["apps"], {"web-app-a": 125.0, "web-app-b": 95.0, "web-app-c": 20.0}
        )
        self.assertEqual(result["fixed"], 20.0)
        self.assertEqual(result["total"], 260.0)

    def test_negative_control_another_apps_task_never_lands_on_this_app(self) -> None:
        result = segments.attribute(
            segments.parse_tsv(TSV), ["web-app-c"], entity_of=_entity
        )
        self.assertEqual(result["apps"], {"web-app-c": 60.0})
        self.assertEqual(result["fixed"], 200.0)

    def test_an_app_no_task_reaches_stays_unpriced_in_a_tsv(self) -> None:
        tasks = segments.parse_tsv("100\t1\tweb-app-a : own task")
        result = segments.attribute(
            tasks, ["web-app-a", "web-app-z"], entity_of=_entity
        )
        self.assertEqual(result["apps"], {"web-app-a": 100.0})

    def test_a_log_pass_is_cut_at_each_apps_first_task(self) -> None:
        result = segments.first_task_segments(LOG, APPS)
        self.assertEqual(result["apps"], {"web-app-a": 50.0, "web-app-b": 60.0})

    def test_a_log_pass_splits_fixed_app_and_e2e_time(self) -> None:
        result = segments.first_task_segments(LOG, APPS)
        self.assertEqual(
            (result["fixed"], result["e2e"], result["total"]), (10.0, 180.0, 300.0)
        )

    def test_negative_control_an_app_the_pass_never_reached_is_not_priced_at_zero(
        self,
    ) -> None:
        result = segments.first_task_segments(LOG, APPS)
        self.assertNotIn("web-app-c", result["apps"])
        self.assertEqual(result["unseen"], ["web-app-c"])

    def test_no_log_text_leaves_the_segments(self) -> None:
        self.assertNotIn("hunter2", repr(segments.first_task_segments(LOG, APPS)))

    def test_negative_control_a_log_without_headers_prices_nothing(self) -> None:
        result = segments.first_task_segments(["no header here"], ["web-app-a"])
        self.assertEqual((result["apps"], result["total"]), ({}, 0.0))
        self.assertEqual(result["unseen"], ["web-app-a"])

    def test_a_cut_pass_marks_the_file_a_lower_bound(self) -> None:
        data = segments.build(
            {"1": TSV, "2": TSV},
            ["web-app-a"],
            entity_of=_entity,
            runner="r1",
            cut=["2"],
            source="run 1",
        )
        self.assertTrue(data["lower_bound"])
        self.assertIn("lower bound", data["source"])

    def test_a_file_names_its_runner(self) -> None:
        data = segments.build_from_log(LOG, {"1": (1, None)}, APPS, runner="r1")
        self.assertEqual(data["runner"], "r1")


class TestMerge(unittest.TestCase):
    def test_a_later_file_prices_only_the_gaps_of_its_runner(self) -> None:
        merged = segments.merge(
            [
                _file("r1", {"2": {"web-app-a": 10.0}}),
                _file("r1", {"2": {"web-app-a": 99.0, "web-app-b": 20.0}}),
            ]
        )
        self.assertEqual(
            merged["passes"], {"2": {"web-app-a": 10.0, "web-app-b": 20.0}}
        )

    def test_negative_control_files_of_two_runners_are_never_mixed(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be merged"):
            segments.merge([_file("fast", {}), _file("slow", {})])

    def test_a_lower_bound_file_makes_the_merge_a_lower_bound(self) -> None:
        merged = segments.merge([_file("r1", {}), _file("r1", {}, cut=True)])
        self.assertTrue(merged["lower_bound"])

    def test_nothing_to_merge_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            segments.merge([])


if __name__ == "__main__":
    unittest.main()
