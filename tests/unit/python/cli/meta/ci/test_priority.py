from __future__ import annotations

import io
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

from cli.administration.deploy.ci import gh, runs
from cli.meta.ci.priority import __main__ as priority
from tests.unit.python.cli.administration.deploy.ci.test_trigger import (
    _FAILED_TOKENS,
    _RUN_URL,
    _SOURCE_RUN,
    _job,
)

_NEVER_DEPLOYED = "web-app-z#1@compose+tor"


class TestPriorityLine(unittest.TestCase):
    def _run(self, source: dict, inputs: dict[str, str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=source),
            mock.patch.object(runs, "inputs_from_jobs", return_value=inputs),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = priority.main([_RUN_URL])
        return rc, out.getvalue(), err.getvalue()

    def test_failed_and_never_deployed_entries_print_on_one_line(self) -> None:
        rc, out, _ = self._run(_SOURCE_RUN, {"priority": _NEVER_DEPLOYED})
        self.assertEqual(rc, 0)
        self.assertEqual(
            out,
            " ".join(sorted([*_FAILED_TOKENS.split(), _NEVER_DEPLOYED])) + "\n",
        )

    def test_a_green_run_prints_nothing(self) -> None:
        green = {
            "jobs": [_job("docker", "web-app-x", "success")],
            "displayTitle": _SOURCE_RUN["displayTitle"],
        }
        rc, out, err = self._run(green, {})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertIn("Nothing failed", err)


if __name__ == "__main__":
    unittest.main()
