from __future__ import annotations

import io
import json
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from cli.meta.ci.iterate import __main__ as entry
from cli.meta.ci.iterate import diff
from cli.meta.ci.iterate.render import render
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from ._catalog_fixture import FakeCatalog

PATHS = [f"roles/web-app-light/{ROLE_FILE_TASKS_MAIN}", "docs/a.md"]


def _content(ref: str, path: str) -> str:
    return "a: 1\n" if ref else "a: 2\n"


def _plan(**options) -> dict:
    values = {"loop": "", "disable": "", "timings": ""}
    values.update(options)
    with (
        mock.patch.object(diff, "changed_paths", return_value=PATHS),
        mock.patch.object(diff, "content", side_effect=_content),
    ):
        return entry.plan_span(diff.Span("b" * 40, ""), FakeCatalog(), **values)


class TestPlanSpan(unittest.TestCase):
    def test_carries_both_sides_and_the_wall_time(self) -> None:
        result = _plan()
        self.assertEqual((result["base"], result["head"]), ("b" * 40, ""))
        self.assertGreaterEqual(result["elapsed_s"], 0)

    def test_every_path_is_classified(self) -> None:
        self.assertEqual([c["path"] for c in _plan()["changed"]], PATHS)

    def test_plan_holds_the_keys_routines_read(self) -> None:
        self.assertLessEqual(
            {
                "loop",
                "tiers",
                "rows",
                "disable",
                "mode",
                "variant",
                "network",
                "footprint",
                "cost",
                "cuts",
            },
            set(_plan()),
        )


class TestRender(unittest.TestCase):
    def test_human_form_names_every_tier_and_the_cost_source(self) -> None:
        text = render(_plan())
        for marker in (
            "T0 ",
            "T1 ",
            "T2 ",
            "T3 ",
            "footprint:",
            "source: declared",
            "cuts:",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class TestMain(unittest.TestCase):
    def _main(self, *argv: str) -> str:
        out = io.StringIO()
        with (
            mock.patch.object(
                entry.diff, "resolve", return_value=diff.Span("c" * 40, "")
            ),
            mock.patch.object(entry, "Catalog", FakeCatalog),
            mock.patch.object(diff, "changed_paths", return_value=PATHS),
            mock.patch.object(diff, "content", side_effect=_content),
            redirect_stdout(out),
        ):
            self.assertEqual(entry.main(list(argv)), 0)
        return out.getvalue()

    def test_json_format_is_machine_readable(self) -> None:
        self.assertEqual(json.loads(self._main("--format", "json"))["loop"], "compose")

    def test_default_format_is_the_human_form(self) -> None:
        self.assertTrue(self._main().startswith("iterate-plan cccccccccc..worktree"))

    def test_unknown_loop_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            entry.main(["--loop", "k8s"])


if __name__ == "__main__":
    unittest.main()
