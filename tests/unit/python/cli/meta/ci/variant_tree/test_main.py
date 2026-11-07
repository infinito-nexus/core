from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from cli.meta.ci.variant_tree import __main__ as cli
from cli.meta.ci.variant_tree import tree

FOUR = {"web-app-a": [{}, {}, {}, {}]}
BUILT = {
    "primary": "web-app-a#1",
    "round_index": 1,
    "include_count": 1,
    "error": None,
    "nodes": [
        {
            "role": "web-app-a",
            "variant": 1,
            "variants": 4,
            "reason": "primary",
            "services": [],
            "children": [],
        }
    ],
}
AXES = {"0": {"entries": [], "job_position": 3, "in_budget_head": True, "covered": "0"}}


class TestMain(unittest.TestCase):
    def _run(
        self, *argv: str, built: dict | None = None
    ) -> tuple[int, str, str, mock.Mock]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("utils.cache.applications.get_variants", return_value=FOUR),
            mock.patch.object(tree, "build", wraps=tree.build) as build,
            mock.patch(
                "cli.meta.ci.variant_split.snapshot.row_axes", return_value=AXES
            ) as axes,
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            if built is not None:
                build.side_effect = None
                build.return_value = built
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue(), axes

    def test_negative_control_a_variant_past_the_last_fails_naming_the_range(
        self,
    ) -> None:
        rc, out, err, _ = self._run("web-app-a#9")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("must be 0..3", err)

    def test_the_json_form_carries_the_axes_of_each_sweep(self) -> None:
        rc, out, _, _ = self._run("web-app-a#1", "--json", built=dict(BUILT))
        self.assertEqual((rc, json.loads(out)["axes"]), (0, AXES))

    def test_an_empty_sweep_list_skips_the_axes(self) -> None:
        _, _, _, axes = self._run("web-app-a#1", "--sweeps", "", built=dict(BUILT))
        axes.assert_not_called()

    def test_the_text_form_leads_with_the_row(self) -> None:
        rc, out, _, _ = self._run("web-app-a#1", built=dict(BUILT))
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("web-app-a#1: include 1"))

    def test_negative_control_a_pin_error_exits_1(self) -> None:
        failed = {**BUILT, "error": "pins cycle", "nodes": []}
        rc, out, _, axes = self._run("web-app-a#1", built=failed)
        self.assertEqual(rc, 1)
        self.assertIn("error: pins cycle", out)
        axes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
